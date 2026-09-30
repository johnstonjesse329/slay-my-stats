# Site pages

Each `.html` file here is a page on the site, at the address of its file name: `about.html` is
`slay-my-stats.com/about`. Write plain HTML: `<h1>` for the title (it also becomes the browser tab's title),
`<h2>` for sections, `<p>` for paragraphs, `<a href="...">` for links. Add `target="_blank"` to a link to open
it in a new tab.

To list a page in the site bar, make its first line `<!-- nav: Label -->`. Pages without it are still there,
just not linked from the bar.

File names: lowercase letters, digits and dashes only, and not a name the site already uses (`u`, `users`,
`api`, or an art folder like `thumbs`). The build stops with a message if one isn't allowed.

The home page's intro, above the player search, is `site/home-intro.html`, written the same way.

Preview: `python tools/serve_site.py`, then open `http://localhost:8000/about`. Edits, and new pages, show
up when you refresh. On the live site a new page also changes the CloudFront setup, which the push asks you
to confirm.
