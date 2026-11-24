extends Node2D

# Renders one image per encounter: every monster in the fight, placed and scaled
# the way the game places it. Reads manifest.json (built by build_manifest.py)
# and loads the .atlas/.skel straight out of the PCK extraction.

const CANVAS := Vector2i(2600, 1600)
const PAD := 12
const IDLE_PREFERENCE := ["idle_loop", "idle", "idle_a", "Idle"]
# NCombatRoom.PositionEnemies: monsters sit on this baseline, spaced by their
# own footprint width plus this gap, every other one raised when it gets tight.
const BASELINE := 200.0
const GAP := 70.0

var _pck := ""
var _out := ""

func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	_pck = args[0]
	_out = args[1]
	DirAccess.make_dir_recursive_absolute(_out)
	var manifest: Dictionary = JSON.parse_string(
		FileAccess.get_file_as_string(args[2]))["encounters"]
	var keys := manifest.keys()
	keys.sort()
	for key in keys:
		await _render(key, manifest[key])
	get_tree().quit()

func _pick_idle(anims: Array[String]) -> String:
	for want in IDLE_PREFERENCE:
		if want in anims:
			return want
	for a in anims:
		if a.contains("idle"):
			return a
	for a in anims:
		if a != "empty":
			return a
	return ""

func _sprite_for(m: Dictionary) -> Node:
	var atlas: Resource = ClassDB.instantiate("SpineAtlasResource")
	atlas.call("load_from_atlas_file", _pck + "/" + m["atlas"])
	var skel: Resource = ClassDB.instantiate("SpineSkeletonFileResource")
	skel.call("load_from_file", _pck + "/" + m["skel"])
	var data: Resource = ClassDB.instantiate("SpineSkeletonDataResource")
	data.call("set_atlas_res", atlas)
	data.call("set_skeleton_file_res", skel)
	if not data.call("is_skeleton_data_loaded"):
		return null
	var sprite: Node = ClassDB.instantiate("SpineSprite")
	sprite.set("skeleton_data_res", data)
	# The scene's preview_skin is what the game shows; without it a skinned
	# skeleton (the scrolls, the kin) draws nothing but its shadow.
	var skin := String(m.get("skin", ""))
	if skin != "" and skin.to_lower() != "default":
		var skeleton: Object = sprite.call("get_skeleton")
		if skeleton != null:
			# set_skin takes a SpineSkin; by name is what we have from the scene.
			skeleton.call("set_skin_by_name", skin)
			skeleton.call("set_slots_to_setup_pose")
	var anims: Array[String] = []
	for a in data.call("get_animations"):
		anims.append(String(a.call("get_name")))
	var pick := _pick_idle(anims)
	if pick != "":
		sprite.call("get_animation_state").call("set_animation", pick, true, 0)
	return sprite

# Mirrors NCombatRoom.PositionEnemies for encounters with no scene of their own.
func _default_positions(monsters: Array, scaling: float) -> Array[Vector2]:
	var avail := 960.0 / scaling
	var gap := GAP
	var total_w := 0.0
	for m in monsters:
		total_w += float(m["width"])
	var span := total_w + (monsters.size() - 1) * gap
	var x := maxf((avail - span) * 0.5, 150.0)
	var raise := 0.0
	if x + span > avail and monsters.size() > 1:
		gap = maxf((avail - 150.0 - total_w) / (monsters.size() - 1), 5.0)
		span = total_w + (monsters.size() - 1) * gap
		x = (avail - span) * 0.5
		if gap < 30.0:
			raise = lerpf(60.0, 40.0, (gap - 5.0) / 25.0)
	var out: Array[Vector2] = []
	for i in monsters.size():
		out.append(Vector2(x + float(monsters[i]["width"]) * 0.5,
			BASELINE - (raise if i % 2 != 0 else 0.0)))
		x += float(monsters[i]["width"]) + gap
	return out

func _render(key: String, enc: Dictionary) -> void:
	var monsters: Array = []
	for m in enc["monsters"]:
		if not m.get("missing", false):
			monsters.append(m)
	if monsters.is_empty():
		print("SKIP %s: nothing to draw" % key)
		return

	var scaling := float(enc["camera_scaling"])
	var placed: Array[Vector2] = []
	var slotted := true
	for m in monsters:
		if m["pos"] == null:
			slotted = false
	if slotted:
		for m in monsters:
			placed.append(Vector2(m["pos"][0], m["pos"][1]))
	else:
		placed = _default_positions(monsters, scaling)

	var vp := SubViewport.new()
	vp.size = CANVAS
	vp.transparent_bg = true
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(vp)
	var group := Node2D.new()
	group.scale = Vector2(scaling, scaling)
	vp.add_child(group)

	var drawn := 0
	for i in monsters.size():
		var m: Dictionary = monsters[i]
		var sprite := _sprite_for(m)
		if sprite == null:
			print("  %s: %s failed to load" % [key, m["id"]])
			continue
		group.add_child(sprite)
		sprite.set("scale", Vector2(float(m["scale"][0]), float(m["scale"][1])))
		sprite.set("position", placed[i] + Vector2(float(m["offset"][0]), float(m["offset"][1])))
		sprite.call("update_skeleton", 0.0)
		drawn += 1
	if drawn == 0:
		vp.queue_free()
		return

	# Centre the group in the canvas before capturing: slot coordinates are in
	# the game's 1920x1080 scene space, which the canvas is deliberately larger
	# than so nothing is lost off an edge.
	var rect := Rect2()
	var first := true
	for child in group.get_children():
		var b: Rect2 = child.call("get_skeleton").call("get_bounds")
		b.position = b.position * child.scale + child.position
		b.size = b.size * child.scale
		b = b.abs()
		rect = b if first else rect.merge(b)
		first = false
	# A group bigger than the canvas (the largest bosses) is scaled down to fit
	# rather than cropped, so no fight loses an edge.
	var fit := 1.0
	var span := rect.size * scaling
	if span.x > 0.0 and span.y > 0.0:
		fit = minf(1.0, minf((CANVAS.x - 4 * PAD) / span.x, (CANVAS.y - 4 * PAD) / span.y))
	group.scale = Vector2(scaling * fit, scaling * fit)
	group.position = Vector2(CANVAS) * 0.5 - rect.get_center() * scaling * fit

	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw

	var img: Image = vp.get_texture().get_image()
	var used := img.get_used_rect()
	if used.size == Vector2i.ZERO:
		print("EMPTY %s" % key)
		vp.queue_free()
		return
	var clipped := used.position.x <= 0 or used.position.y <= 0 \
		or used.end.x >= CANVAS.x or used.end.y >= CANVAS.y
	used = used.grow(PAD).intersection(Rect2i(Vector2i.ZERO, CANVAS))
	img.get_region(used).save_png("%s/%s.png" % [_out, key.to_lower().replace(".", "_")])
	print("OK %s  %dx%d  n=%d  %s  clipped=%s" % [
		key, used.size.x, used.size.y, drawn,
		"slots" if slotted else "default", clipped])
	vp.queue_free()
