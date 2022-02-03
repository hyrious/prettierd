# Sublime Text Plugin Prettierd

Faster <q>format on save</q>.

## Why?

[JsPrettier](https://github.com/jonlabelle/SublimeJsPrettier) is very slow.
It blocks your main thread.

This plugin solves this problem by spawning a prettier daemon.

## Install

This plugin **ONLY** supports Sublime Text 4 currently. Sorry for st2/st3 users.
If you want it to work on st2/st3, welcome to submit a PR!

Make sure you have installed `node` and `prettier` (with `npm i -g`) globally.

<kbd>Ctrl/CMD + Shift + P</kbd>, `Package Control: Add Repository`, paste this link:

    https://github.com/hyrious/prettierd

Then your editing file will be formatted on save.

## Configure

<kbd>Ctrl/CMD + Shift + P</kbd>, `Preferences: Prettier`.

## License

MIT @ [hyrious](https://github.com/hyrious)
