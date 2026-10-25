// Installed by LXMaxAnimation. Editor only; never runs in a player build.
using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace LXMaxAnimation
{
    [InitializeOnLoad]
    public static class Receiver
    {
        [Serializable] private class Request { public string id; public string path; public string rig; }
        [Serializable] private class Result { public bool ok; public string message; }
        private static double next;
        static Receiver() { EditorApplication.update += Tick; }
        private static void Tick()
        {
            if (EditorApplication.timeSinceStartup < next || EditorApplication.isCompiling || EditorApplication.isUpdating || EditorApplication.isPlayingOrWillChangePlaymode) return;
            next = EditorApplication.timeSinceStartup + 1;
            var queue = Path.GetFullPath("Library/LXMaxAnimation/queue");
            if (!Directory.Exists(queue)) return;
            foreach (var file in Directory.GetFiles(queue, "*.request.json"))
            {
                var result = new Result();
                try
                {
                    var request = JsonUtility.FromJson<Request>(File.ReadAllText(file));
                    var root = Path.GetFullPath("Assets/LXMaxAnimation/Library") + Path.DirectorySeparatorChar;
                    var full = Path.GetFullPath(request.path);
                    if (!full.StartsWith(root, StringComparison.OrdinalIgnoreCase) || Path.GetExtension(full).ToLowerInvariant() != ".fbx" || !File.Exists(full))
                        throw new Exception("Invalid or missing library FBX.");
                    AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                    AssetDatabase.ImportAsset(request.path, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
                    var importer = AssetImporter.GetAtPath(request.path) as ModelImporter;
                    if (importer == null) throw new Exception("FBX importer unavailable.");
                    importer.importAnimation = true;
                    importer.animationType = request.rig == "Humanoid" ? ModelImporterAnimationType.Human : ModelImporterAnimationType.Generic;
                    importer.SaveAndReimport();
                    var model = AssetDatabase.LoadAssetAtPath<GameObject>(request.path);
                    if (model == null) throw new Exception("FBX did not produce a model asset.");
                    if (request.rig == "Humanoid")
                    {
                        bool validAvatar = false;
                        foreach (var obj in AssetDatabase.LoadAllAssetsAtPath(request.path))
                            if (obj is Avatar avatar && avatar.isValid && avatar.isHuman) validAvatar = true;
                        if (!validAvatar) throw new Exception("Humanoid Avatar invalid. Configure the rig mapping in Unity.");
                    }
                    Selection.activeObject = model;
                    EditorGUIUtility.PingObject(model);
                    result.ok = true;
                    result.message = "Unity imported: " + request.path;
                }
                catch (Exception ex) { result.ok = false; result.message = ex.Message; Debug.LogError("LXMaxAnimation: " + ex); }
                var target = file.Replace(".request.json", ".result.json");
                File.WriteAllText(target + ".tmp", JsonUtility.ToJson(result));
                if (File.Exists(target)) File.Delete(target);
                File.Move(target + ".tmp", target);
                File.Delete(file);
            }
        }
    }
}
