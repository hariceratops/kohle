# Regenerate from the repository root: uv run vhs docs/demo/taste.tape
# Needs the system tools vhs, ttyd and ffmpeg. Not Python dependencies.
# The typed commands mirror the README "A taste" block: change this tape and
# that block together.

Output docs/demo/taste.gif

Set Shell bash
Set FontSize 16
Set Width 1200
Set Height 700
Set TypingSpeed 40ms

Hide
Type `PS1='$ '` Enter
Type `D=$(mktemp -d); export KOHLE_DB=$D/kohle.db XDG_CONFIG_HOME=$D/config` Enter
Type `mkdir -p $D/config/kohle; printf 'state = "BW"\n' > $D/config/kohle/init.toml` Enter
Type `kohle-cli init >/dev/null; cp docs/examples/* $D/; cd $D; clear` Enter
Show

Type "kohle-cli add-account Checking --type asset" Enter
Sleep 1500ms
Type "kohle-cli add-account Rent --type expense" Enter
Sleep 1500ms
Type "kohle-cli add-account Groceries --type expense" Enter
Sleep 1500ms
Type "kohle-cli add-account Salary --type income" Enter
Sleep 1500ms
Type "kohle-cli apply-rules rules.toml --yes" Enter
Sleep 3s
Type "kohle-cli import-statement kohle-deutsche-bank Checking statement.csv" Enter
Sleep 2s
Type "kohle-cli balance Groceries" Enter
Sleep 5s

# Change this tape and the README "A taste" block together.
