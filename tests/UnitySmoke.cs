using System;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;
public static class LXAnimationSmoke
{
    public static void Run()
    {
        typeof(LXMaxAnimation.Receiver).GetMethod("Tick",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,null);
        var results=Directory.GetFiles("Library/LXMaxAnimation/queue","*.result.json");
        if(results.Length<2)throw new Exception("Missing import receipts");
        foreach(var result in results)
            if(!File.ReadAllText(result).Contains("\"ok\":true"))throw new Exception(File.ReadAllText(result));
        int clips=0;
        foreach(var guid in AssetDatabase.FindAssets("t:Model",new[]{"Assets/LXMaxAnimation/Library"}))
        {
            string path=AssetDatabase.GUIDToAssetPath(guid);
            foreach(var asset in AssetDatabase.LoadAllAssetsAtPath(path))
                if(asset is AnimationClip clip && !clip.name.StartsWith("__preview__") && clip.length>0)clips++;
        }
        if(clips<1)throw new Exception("No non-empty animation clips imported");
        File.WriteAllText("../unity-smoke-result.json","{\"ok\":true,\"receipts\":"+results.Length+",\"clips\":"+clips+"}");
        Debug.Log("LXMaxAnimation integration PASSED: "+clips+" animation clips");
    }
}
