#!/bin/bash
# Change to resource directory for command execution
cd /home/user/axi-game-engine
source ~/.bashrc 2>/dev/null || source ~/.profile 2>/dev/null
export TERM=xterm-256color
session_name="command_0_73b015ad"
is_attached() {
    # Returns 0 if attached, non-zero otherwise
    screen -list | grep "$session_name" | grep -q "Attached"
    return $?
}
while ! is_attached; do
    sleep 0.5
done
sleep 1
python3 -m metaclaude.utils.dummy_process 2> "/home/user/axi-game-engine/logs/cmd_error_0.log"
exit_status=$?
echo "Exit status of command python3 -m metaclaude.utils.dummy_process: $exit_status" > /home/user/axi-game-engine/logs/cmd_exit_status_0.log
exit $exit_status
