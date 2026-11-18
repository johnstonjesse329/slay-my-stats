# What's new posts

Each `.html` file here is one post on the [What's new](/whats-new) page, newest first. Name it
`<YYYY-MM-DD>-<id>.html`: the date is the one the page shows, and the id is the post's own link,
`slay-my-stats.com/whats-new/<id>` (lowercase letters, digits and dashes, at most 60 characters,
used once). Keep the id once a post is up: its reactions are stored under it.

The wording is the owner's: draft or suggest edits if asked, trim and organize freely, but keep their
voice and don't invent detail (see `CLAUDE.md`).

Start the file with a comment that names the post, then write plain HTML, as for a site page
(`site/pages/README.md`): `<p>`, `<ul>`, `<a href>`, `<img src>`.

```html
<!--
title: Drag across a run's charts to add up a stretch
fixes: FB-12, FB-31
-->
<p>Pick a span on any floor chart and a panel adds up what changed in it.</p>
```

`title` is required. `fixes` is optional: the feedback notes this post closes. The post then says
how many players asked for it (their +1s on those notes), and players who filed or +1'd one see
"You asked for this" on it.

The page's own heading and intro are `site/pages/whats-new.html`; the posts go where it says
`<!-- posts -->`. `python build_site.py` stops with a message if a file name or header is wrong.
Preview with `python tools/serve_site.py` and open `http://localhost:8000/whats-new`. Reactions
need the live site: they're stored in DynamoDB (`infra/lambda/ingest/reactions.py`).

A new post changes `index.html` too (the site bar's new-post dot), so it reaches everyone with
the next deploy.
