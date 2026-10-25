-- Run this script in the Max instance that should receive commands.
(
    local bridge = (getFilenamePath (getSourceFileName())) + "bridge.py"
    python.ExecuteFile bridge
)
