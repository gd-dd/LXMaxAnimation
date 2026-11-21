-- Invoked by Max at launch or by the shared idle connector.
global LXMaxAutoConnectRoot
global LXMaxAutoConnectTimer
global LXMaxAnimationBootstrapSource
(
    local source = getSourceFileName()
    local directory = getFilenamePath source
    if LXMaxAutoConnectRoot == undefined do
    (
        local environment = dotNetClass "System.Environment"
        local data = environment.GetEnvironmentVariable "LOCALAPPDATA"
        if data == undefined do data = environment.GetFolderPath ((dotNetClass "System.Environment+SpecialFolder").LocalApplicationData)
        LXMaxAutoConnectRoot = (dotNetClass "System.IO.Path").Combine data "LXMaxTools"
    )
    local dispatcher = directory + "auto_connect.ms"
    if LXMaxAutoConnectTimer == undefined and doesFileExist dispatcher do fileIn dispatcher quiet:true
    if not (python.ExecuteFile (directory + "bridge.py")) do throw "LX Animation bridge initialization failed"
    LXMaxAnimationBootstrapSource = source
)
