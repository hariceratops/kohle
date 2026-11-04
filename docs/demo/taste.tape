# Regenerate from the repository root: uv run vhs docs/demo/taste.tape
# Needs the system tools vhs, ttyd and ffmpeg. Not Python dependencies.
# The typed commands mirror the README "A taste" block: change this tape and
# that block together.

Output docs/demo/taste.gif

Set Shell bash
Set FontSize 15
Set Width 1500
Set Height 640
Set WaitPattern /\$$/
Set TypingSpeed 40ms

Hide
Type `PS1='$ '` Enter
Type `D=$(mktemp -d); export KOHLE_DB=$D/kohle.db XDG_CONFIG_HOME=$D/config` Enter
Type `mkdir -p $D/config/kohle; printf 'state = "BW"\n' > $D/config/kohle/init.toml` Enter
Type `kohle-cli init >/dev/null; cp docs/examples/* $D/; cd $D; clear` Enter
Show

Type "kohle-cli add-account Checking --type asset" Enter
Wait
Sleep 1s
Type "kohle-cli add-account Rent --type expense" Enter
Wait
Sleep 1s
Type "kohle-cli add-account Groceries --type expense" Enter
Wait
Sleep 1s
Type "kohle-cli add-account Salary --type income" Enter
Wait
Sleep 1s
Type "kohle-cli apply-rules rules.toml --yes" Enter
Wait
Sleep 1s
Type "kohle-cli import-statement kohle-deutsche-bank Checking statement.csv" Enter
Wait
Sleep 1s
Type "kohle-cli balance Groceries" Enter
Wait
Sleep 1s

# Change this tape and the README "A taste" block together.
Sleep 4s
