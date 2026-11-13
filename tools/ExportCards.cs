// Slay My Stats exporter: runs inside the recovered Slay the Spire 2 Godot project
// (pck_recover_full/) as an autoload and asks the game itself for what the site shows.
//
//   * card_game_data.json -- every card, relic, potion and enchantment, with the text
//     the game's own formatters produce and the real decimal values of its variables.
//   * card_final/*.webp   -- every card face, drawn by the game's own card scene.
//
// It is inert unless EXPORT_CARDS=1, so the autoload is harmless in the real game.
//
// Environment:
//   EXPORT_CARDS=1        run at all
//   RENDER_ALL=1          render every card, base and upgraded
//   EXPORT_MADSCIENCE=1   also render and export Mad Science's nine per-roll variants
//   CARD_IDS=A,B          render only these entries (e.g. BASH,TANK)
//   RENDER_LIMIT=n        stop after n images (quick layout iterations)
//   EXPORT_DIR=path       where to write (default: the project's user:// card_export)
//
// Output goes to <user dir>/card_export. tools/export_game_data.py installs this file
// into the recovery (it lives in the slay-my-stats repo, because the recovery is thrown
// away and rebuilt on every game update), builds, runs it and copies the output.
// The success line "[export] card_game_data.json:" is what that driver looks for.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Threading.Tasks;
using Godot;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Localization;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.Models.Events;
using MegaCrit.Sts2.Core.Nodes.Cards;

public partial class ExportCards : Node
{
	private const int FaceWidth = 332;   // a 300x422 card plus the room its shadow needs
	private const int FaceHeight = 454;

	private string _outDir = "";
	private static readonly JsonSerializerOptions Json = new()
	{
		WriteIndented = true,
		Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
	};

	public override void _Ready()
	{
		if (System.Environment.GetEnvironmentVariable("EXPORT_CARDS") != "1")
		{
			return;
		}
		_outDir = System.Environment.GetEnvironmentVariable("EXPORT_DIR")
			?? ProjectSettings.GlobalizePath("user://card_export");
		Directory.CreateDirectory(_outDir);
		GD.Print($"[export] output dir = {_outDir}");
		_ = RunAsync();
	}

	private async Task RunAsync()
	{
		int exitCode = 0;
		try
		{
			await WaitForGame();
			Dictionary<string, object?> root = ExportData(out List<CardModel> cards, out int upgradable);
			WriteJson("card_game_data.json", root);
			var pools = (List<string>)root["CharacterPools"]!;
			GD.Print($"[export] card_game_data.json: {cards.Count} cards, {upgradable} upgradable, "
				+ $"{((List<object>)root["Relics"]!).Count} relics, {((List<object>)root["Potions"]!).Count} potions, "
				+ $"{((List<object>)root["Enchantments"]!).Count} enchantments, character pools: {string.Join(", ", pools)}");

			bool renderAll = Env("RENDER_ALL");
			bool madScience = Env("EXPORT_MADSCIENCE");
			string? ids = System.Environment.GetEnvironmentVariable("CARD_IDS");
			if (renderAll || madScience || !string.IsNullOrEmpty(ids))
			{
				await RenderFaces(cards, renderAll, madScience, ids);
			}
			else
			{
				GD.Print("[export] nothing to render; set CARD_IDS, EXPORT_MADSCIENCE and/or RENDER_ALL");
			}
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[export] FAILED: {ex}");
			exitCode = 1;
		}
		GetTree().Quit(exitCode);
	}

	private static bool Env(string name) => System.Environment.GetEnvironmentVariable(name) == "1";

	/// <summary>The game's models need the localisation tables loaded; wait for the game to get there.</summary>
	private async Task WaitForGame()
	{
		for (int attempt = 0; attempt < 120; attempt++)
		{
			await ToSignal(GetTree().CreateTimer(1.0), SceneTreeTimer.SignalName.Timeout);
			try
			{
				if (LocManager.Instance != null && ModelDb.AllCharacters.Any()
					&& LocString.Exists("cards", "BASH.title"))
				{
					// A few more frames so the atlases the card scene draws from are in.
					await ToSignal(GetTree().CreateTimer(2.0), SceneTreeTimer.SignalName.Timeout);
					return;
				}
			}
			catch (Exception)
			{
				// Not ready yet.
			}
		}
		throw new InvalidOperationException("the game's localisation never finished loading");
	}

	private void WriteJson(string name, object value)
	{
		File.WriteAllText(Path.Combine(_outDir, name), JsonSerializer.Serialize(value, Json), new UTF8Encoding(false));
	}

	// ---------------------------------------------------------------------------------
	// data
	// ---------------------------------------------------------------------------------

	private static Dictionary<string, decimal> VarsOf(DynamicVarSet set)
	{
		var vars = new Dictionary<string, decimal>();
		foreach (KeyValuePair<string, DynamicVar> kv in set)
		{
			vars[kv.Key] = kv.Value.BaseValue;
		}
		return vars;
	}

	private static List<string> KeywordNames(IEnumerable<CardKeyword> keywords)
		=> keywords.Select(k => k.ToString()).ToList();

	private static string Text(CardModel card) => card.GetDescriptionForPile(PileType.None);

	private Dictionary<string, object?> ExportData(out List<CardModel> cards, out int upgradable)
	{
		cards = ModelDb.AllCards.OrderBy(c => c.Id.Entry, StringComparer.Ordinal).ToList();
		int up = 0;
		var cardRecords = new List<object>();
		foreach (CardModel card in cards)
		{
			try
			{
				var record = ExportCard(card);
				if (record["UpgradeError"] == null)
				{
					up++;
				}
				cardRecords.Add(record);
			}
			catch (Exception ex)
			{
				GD.PrintErr($"[export] skipped card {card.Id.Entry}: {ex.Message}");
			}
		}
		upgradable = up;

		var relics = new List<object>();
		foreach (RelicModel relic in ModelDb.AllRelics.OrderBy(r => r.Id.Entry, StringComparer.Ordinal))
		{
			try
			{
				LocString description = relic.DynamicDescription;
				relics.Add(new Dictionary<string, object?>
				{
					["Entry"] = relic.Id.Entry,
					["Title"] = relic.Title.GetFormattedText(),
					["Rarity"] = relic.Rarity.ToString(),
					["Description"] = description.GetFormattedText(),
					["RawText"] = description.GetRawText(),
					["Vars"] = VarsOf(relic.DynamicVars),
				});
			}
			catch (Exception ex)
			{
				GD.PrintErr($"[export] skipped relic {relic.Id.Entry}: {ex.Message}");
			}
		}

		var potions = new List<object>();
		foreach (PotionModel potion in ModelDb.AllPotions.OrderBy(p => p.Id.Entry, StringComparer.Ordinal))
		{
			try
			{
				LocString description = potion.DynamicDescription;
				potions.Add(new Dictionary<string, object?>
				{
					["Entry"] = potion.Id.Entry,
					["Title"] = potion.Title.GetFormattedText(),
					["Rarity"] = potion.Rarity.ToString(),
					["Description"] = description.GetFormattedText(),
					["RawText"] = description.GetRawText(),
					["Vars"] = VarsOf(potion.DynamicVars),
				});
			}
			catch (Exception ex)
			{
				GD.PrintErr($"[export] skipped potion {potion.Id.Entry}: {ex.Message}");
			}
		}

		var enchantments = new List<object>();
		foreach (EnchantmentModel enchantment in ModelDb.DebugEnchantments.OrderBy(e => e.Id.Entry, StringComparer.Ordinal))
		{
			try
			{
				enchantments.Add(ExportEnchantment(enchantment));
			}
			catch (Exception ex)
			{
				GD.PrintErr($"[export] skipped enchantment {enchantment.Id.Entry}: {ex.Message}");
			}
		}

		return new Dictionary<string, object?>
		{
			["CharacterPools"] = ModelDb.AllCharacters.Select(c => c.CardPool.Title.ToLowerInvariant()).ToList(),
			["Variants"] = ExportVariants(),
			["Cards"] = cardRecords,
			["Relics"] = relics,
			["Potions"] = potions,
			["Enchantments"] = enchantments,
		};
	}

	private static Dictionary<string, object?> ExportCard(CardModel card)
	{
		CardModel plain = card.ToMutable();
		var record = new Dictionary<string, object?>
		{
			["Entry"] = card.Id.Entry,
			["Title"] = card.Title,
			["Type"] = card.Type.ToString(),
			["Rarity"] = card.Rarity.ToString(),
			["Pool"] = card.Pool.Title.ToLowerInvariant(),
			["Cost"] = plain.EnergyCost.Canonical,
			["CostsX"] = plain.EnergyCost.CostsX,
			["Stars"] = card.CanonicalStarCost,
			["StarsX"] = card.HasStarCostX,
			["EnergyUpgraded"] = 0,
			["StarsUpgraded"] = 0,
			["MaxUpgradeLevel"] = card.MaxUpgradeLevel,
			["ShowInCardLibrary"] = card.ShouldShowInCardLibrary,
			["PortraitPath"] = card.PortraitPath,
			["AllPortraitPaths"] = card.AllPortraitPaths.ToList(),
			["Keywords"] = KeywordNames(card.CanonicalKeywords),
			["Vars"] = VarsOf(plain.DynamicVars),
			["Text"] = Text(plain),
			["KeywordsUpgraded"] = null,
			["VarsUpgraded"] = null,
			["TextUpgraded"] = null,
			["UpgradeError"] = null,
		};
		try
		{
			CardModel upgraded = card.ToMutable();
			upgraded.UpgradeInternal();
			upgraded.FinalizeUpgradeInternal();
			record["EnergyUpgraded"] = upgraded.EnergyCost.Canonical;
			record["StarsUpgraded"] = upgraded.BaseStarCost;
			record["KeywordsUpgraded"] = KeywordNames(upgraded.Keywords);
			record["VarsUpgraded"] = VarsOf(upgraded.DynamicVars);
			record["TextUpgraded"] = Text(upgraded);
		}
		catch (Exception ex)
		{
			record["UpgradeError"] = $"{ex.GetType().Name}: {ex.Message}";
		}
		return record;
	}

	private static Dictionary<string, object?> ExportEnchantment(EnchantmentModel enchantment)
	{
		var descriptions = new Dictionary<string, string>();
		bool cardDependent = false;
		try
		{
			for (int amount = 1; amount <= 6; amount++)
			{
				EnchantmentModel instance = enchantment.ToMutable();
				instance.Amount = amount;
				descriptions[amount.ToString()] = instance.DynamicDescription.GetFormattedText();
			}
		}
		catch (Exception)
		{
			// The text reads a card this canonical copy doesn't have.
			cardDependent = true;
			descriptions.Clear();
		}
		return new Dictionary<string, object?>
		{
			["Entry"] = enchantment.Id.Entry,
			["Title"] = enchantment.Title.GetFormattedText(),
			["IconPath"] = enchantment.IconPath,
			["ShowAmount"] = enchantment.ShowAmount,
			["HasExtraCardText"] = enchantment.HasExtraCardText,
			["CardDependent"] = cardDependent,
			["Descriptions"] = descriptions,
			["ExtraCardTexts"] = new Dictionary<string, string>(),
		};
	}

	// Mad Science is one card whose type and rider are rolled per run, so it has no single
	// text; the nine combinations the game can produce are exported as variants.
	private static readonly (CardType Type, TinkerTime.RiderEffect[] Riders)[] MadScienceRolls =
	{
		(CardType.Attack, new[] { TinkerTime.RiderEffect.Sapping, TinkerTime.RiderEffect.Violence, TinkerTime.RiderEffect.Choking }),
		(CardType.Skill, new[] { TinkerTime.RiderEffect.Energized, TinkerTime.RiderEffect.Wisdom, TinkerTime.RiderEffect.Chaos }),
		(CardType.Power, new[] { TinkerTime.RiderEffect.Expertise, TinkerTime.RiderEffect.Curious, TinkerTime.RiderEffect.Improvement }),
	};

	private static MadScience MadScienceVariant(CardType type, TinkerTime.RiderEffect rider, bool upgraded)
	{
		MadScience card = (MadScience)ModelDb.Card<MadScience>().ToMutable();
		card.TinkerTimeType = type;
		card.TinkerTimeRider = rider;
		if (upgraded)
		{
			card.UpgradeInternal();
			card.FinalizeUpgradeInternal();
		}
		return card;
	}

	private static string VariantKey(CardType type, TinkerTime.RiderEffect rider)
		=> $"CARD.MAD_SCIENCE.{(int)type}.{(int)rider}";

	private static List<object> ExportVariants()
	{
		var variants = new List<object>();
		foreach (var (type, riders) in MadScienceRolls)
		{
			foreach (TinkerTime.RiderEffect rider in riders)
			{
				MadScience plain = MadScienceVariant(type, rider, upgraded: false);
				MadScience upgraded = MadScienceVariant(type, rider, upgraded: true);
				variants.Add(new Dictionary<string, object?>
				{
					["Key"] = VariantKey(type, rider),
					["Entry"] = "MAD_SCIENCE",
					["Type"] = type.ToString(),
					["TypeValue"] = (int)type,
					["Rider"] = rider.ToString(),
					["RiderValue"] = (int)rider,
					["Portrait"] = Path.GetFileNameWithoutExtension(plain.PortraitPath),
					["Text"] = Text(plain),
					["TextUpgraded"] = Text(upgraded),
				});
			}
		}
		return variants;
	}

	// ---------------------------------------------------------------------------------
	// card faces
	// ---------------------------------------------------------------------------------

	private async Task RenderFaces(List<CardModel> cards, bool renderAll, bool madScience, string? ids)
	{
		string faces = Path.Combine(_outDir, "card_final");
		Directory.CreateDirectory(faces);
		int limit = int.TryParse(System.Environment.GetEnvironmentVariable("RENDER_LIMIT"), out int n) ? n : int.MaxValue;
		var wanted = new HashSet<string>((ids ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));

		var viewport = new SubViewport
		{
			Size = new Vector2I(FaceWidth, FaceHeight),
			TransparentBg = true,
			RenderTargetUpdateMode = SubViewport.UpdateMode.Always,
			Disable3D = true,
		};
		AddChild(viewport);
		const string CardScenePath = "res://scenes/cards/card.tscn";
		PackedScene scene = GD.Load<PackedScene>(CardScenePath);

		int written = 0, failed = 0, noUpgrade = 0;
		bool full = renderAll && wanted.Count == 0;

		async Task<bool> Draw(CardModel model, string file)
		{
			NCard? node = null;
			try
			{
				// Something in the game disposes the cached scene wrapper partway through a long
					// run (it was always after about 90 cards), so reload it when that happens.
					if (!GodotObject.IsInstanceValid(scene))
					{
						scene = (PackedScene)ResourceLoader.Load(CardScenePath, "PackedScene", ResourceLoader.CacheMode.Ignore);
					}
					node = scene.Instantiate<NCard>();
				viewport.AddChild(node);
				node.Position = new Vector2(FaceWidth / 2f, FaceHeight / 2f);
				node.Model = model;
				node.UpdateVisuals(PileType.None, CardPreviewMode.None);
				// The description label sizes itself over a couple of frames.
				for (int frame = 0; frame < 4; frame++)
				{
					await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
				}
				Image image = viewport.GetTexture().GetImage();
				return image.SaveWebp(Path.Combine(faces, file), lossy: true, quality: 0.82f) == Error.Ok;
			}
			catch (Exception ex)
			{
				GD.PrintErr($"[render] {file}: {ex.Message}\n{ex.StackTrace}");
				return false;
			}
			finally
			{
				node?.QueueFree();
			}
		}

		bool Tally(bool ok)
		{
			if (ok) written++; else failed++;
			if (ok && written % 100 == 0)
			{
				GD.Print($"[render] {written} images, {failed} failed");
			}
			return written + failed < limit;
		}

		if (renderAll || wanted.Count > 0)
		{
			foreach (CardModel card in cards)
			{
				string entry = card.Id.Entry;
				if (!full && !wanted.Contains(entry))
				{
					continue;
				}
				if (!Tally(await Draw(card.ToMutable(), $"CARD.{entry}.webp")))
				{
					GD.Print($"[render] stopping at RENDER_LIMIT={limit}");
					goto done;
				}
				try
				{
					CardModel upgraded = card.ToMutable();
					upgraded.UpgradeInternal();
					upgraded.FinalizeUpgradeInternal();
					if (!Tally(await Draw(upgraded, $"CARD.{entry}_UP.webp")))
					{
						GD.Print($"[render] stopping at RENDER_LIMIT={limit}");
						goto done;
					}
				}
				catch (InvalidOperationException)
				{
					noUpgrade++;
				}
			}
		}

		if (madScience)
		{
			foreach (var (type, riders) in MadScienceRolls)
			{
				foreach (TinkerTime.RiderEffect rider in riders)
				{
					string key = VariantKey(type, rider);
					Tally(await Draw(MadScienceVariant(type, rider, false), $"{key}.webp"));
					Tally(await Draw(MadScienceVariant(type, rider, true), $"{key}_UP.webp"));
				}
			}
		}

	done:
		viewport.QueueFree();
		GD.Print($"[render] wrote {written} images ({noUpgrade} cards with no upgrade, {failed} failures) to {faces}");
		if (failed > 0)
		{
			throw new InvalidOperationException($"{failed} card faces failed to render");
		}
	}
}
