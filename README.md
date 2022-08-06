# Sublime Text Plugin Prettierd

[Prettier](https://prettier.io) integration for Sublime Text, providing faster <q>format on save</q>.

## Why?

[JsPrettier](https://github.com/jonlabelle/SublimeJsPrettier) is very slow.
It blocks your main thread.

This plugin solves this problem by spawning a prettier daemon.

## Install

You don't have to install JsPrettier to use this plugin.

This plugin **ONLY** supports Sublime Text 4 currently. Sorry for st2/st3 users.
If you want it to work on st2/st3, welcome to submit a PR!

Make sure you have installed `node` and `prettier` (with `npm i -g`) globally.

### Install via Package Control

<kbd>Ctrl/CMD + Shift + P</kbd>, `Package Control: Add Repository`, paste this link:

    https://github.com/hyrious/prettierd

Then run `Package Control: Install Package`, select `prettierd`.

Then your editing file will be formatted on save.

### Install Manually

1. Download and extract the [zip file](https://github.com/hyrious/prettierd/archive/main.zip) to your Sublime Text Packages directory.

   > You can open that folder via `Menu - Preferences - Browse Packages…`,\
   > on Windows it is `%AppData%\Sublime Text\Packages`

2. Rename the extracted directory from prettierd-main to prettierd.

### Install using Git

1. Goto Sublime Text Packages directory.
2. Run `git clone https://github.com/hyrious/prettierd`.

## Configure

<kbd>Ctrl/CMD + Shift + P</kbd>, `Preferences: Prettier`.

## Vendors

[diff-match-patch](https://github.com/google/diff-match-patch) - Apache-2.0 License

## License

MIT @ [hyrious](https://github.com/hyrious)
