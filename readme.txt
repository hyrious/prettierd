WHY?
----
JsPrettier (https://github.com/jonlabelle/SublimeJsPrettier) is very slow.
It blocks your main thread.

This plugin solves this problem by spawning a prettier daemon.


INSTALL
-------
This plugin ONLY supports Sublime Text 4 currently. Sorry for st2/st3 users.
If you want it to work on sublime text 2/3, welcome to submit a PR!

Make sure you have installed `node` and `prettier` (with `npm i -g`) globally.

Ctrl/Command-Shift-P, "Package Control: Add Repository", paste this link:

    https://github.com/hyrious/prettierd

Then your editing file will be formated on save.


CONFIGURE
---------
Ctrl/Command-Shift-P, "Preferences: Prettier".


LICENSE
-------
MIT @ hyrious
