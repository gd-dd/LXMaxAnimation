// Installed by LXMaxAnimation. Editor only.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace LXMaxAnimation
{
    [InitializeOnLoad]
    public static class Receiver
    {
        private const string Queue = "Library/LXMaxAnimation/queue-v2";
        private const string LegacyQueue = "Library/LXMaxAnimation/queue";
        private const string AssetRoot = "Assets/Charactor";
        private static readonly ImportAssetOptions ImportOptions =
            ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate;

        // Unity's serializer populates these fields at runtime.
#pragma warning disable 0649
        [Serializable] private sealed class Request
        {
            public int schema;
            public string id, path, kind, rig, sha256;
            public float sourceFps, sourceStart;
            public Setting[] fbxSettings;
            public Clip[] clips;
        }

        [Serializable] private sealed class Result
        {
            public int schema = 2;
            public bool ok;
            public string id, path, guid, message;
            public int clipCount;
            public string[] warnings;
        }

        [Serializable] private sealed class Setting
        {
            public string name, json;
        }

        [Serializable] private sealed class Clip
        {
            public string id, name, takeName;
            public float firstFrame, lastFrame;
            public Setting[] settings;
        }

        [Serializable] private sealed class ValueBox<T>
        {
            public T value;
        }

        [Serializable] private sealed class EventSetting
        {
            public float frame, floatParameter;
            public int intParameter;
            public string function, stringParameter, objectReference;
        }

        [Serializable] private sealed class CurveSetting
        {
            public string name;
            public CurveKeys curve;
        }

        [Serializable] private sealed class CurveKeys
        {
            public CurveKey[] keys;
        }

        [Serializable] private sealed class CurveKey
        {
            public float time, value, inTangent, outTangent, inWeight, outWeight;
            public int weightedMode;
        }

        [Serializable] private sealed class MaskEntry
        {
            public string path;
            public bool active;
        }

        [Serializable] private sealed class MaterialRemap
        {
            public string sourceName, type, targetGuid, targetPath;
        }
#pragma warning restore 0649

        private static double next;
        private static bool busy;

        static Receiver()
        {
            EditorApplication.update += Tick;
        }

        private static void Tick()
        {
            if (busy || EditorApplication.timeSinceStartup < next || EditorApplication.isCompiling
                || EditorApplication.isUpdating || EditorApplication.isPlayingOrWillChangePlaymode)
                return;
            next = EditorApplication.timeSinceStartup + 1;
            ProcessPending(singleRequest: true);
        }

        public static void RunBatch()
        {
            int failures = ProcessPending();
            if (failures > 0)
                EditorApplication.Exit(1);
        }

        private static int ProcessPending(bool singleRequest = false)
        {
            if (busy || (!Directory.Exists(Queue) && !Directory.Exists(LegacyQueue)))
                return 0;
            busy = true;
            int failures = 0;
            try
            {
                var pending = PendingFiles(Queue).Concat(PendingFiles(LegacyQueue));
                foreach (var file in singleRequest ? pending.Take(1) : pending)
                    if (!ProcessRequest(file))
                        failures++;
            }
            catch (Exception error)
            {
                Debug.LogError("LXMaxAnimation: " + error.Message);
                failures++;
            }
            finally
            {
                busy = false;
            }
            return failures;
        }

        private static IEnumerable<string> PendingFiles(string queue)
        {
            if (!Directory.Exists(queue))
                return Array.Empty<string>();
            return Directory.GetFiles(queue, "*.request.json").OrderBy(File.GetLastWriteTimeUtc)
                .ThenBy(path => path, StringComparer.Ordinal);
        }

        private static bool ProcessRequest(string file)
        {
            string id = Path.GetFileName(file).Substring(0, Path.GetFileName(file).Length - ".request.json".Length);
            string queue = Path.GetDirectoryName(file);
            bool legacy = string.Equals(Path.GetFullPath(queue), Path.GetFullPath(LegacyQueue),
                                        StringComparison.OrdinalIgnoreCase);
            string receipt = Path.Combine(queue, id + ".result.json");
            if (File.Exists(receipt))
            {
                File.Delete(file);
                return JsonUtility.FromJson<Result>(File.ReadAllText(receipt)).ok;
            }
            var warnings = new List<string>();
            var result = new Result { id = id };
            try
            {
                var request = JsonUtility.FromJson<Request>(File.ReadAllText(file));
                if (request == null || request.id != id || !Guid.TryParseExact(id, "N", out _))
                    throw new InvalidDataException("导入任务的编号无效。");
                if (request.schema != (legacy ? 0 : 2))
                    throw new InvalidDataException("此 Unity 导入任务版本不受支持。");
                result.path = request.path;
                Import(request, result, warnings, legacy);
                result.ok = true;
                result.message = "已在 Unity 导入 " + result.path;
            }
            catch (Exception error)
            {
                result.ok = false;
                result.message = error.Message;
                Debug.LogWarning("LXMaxAnimation: " + error.Message);
            }
            result.warnings = warnings.ToArray();
            string temporary = receipt + ".tmp";
            File.WriteAllText(temporary, JsonUtility.ToJson(result, true));
            File.Move(temporary, receipt);
            File.Delete(file);
            return result.ok;
        }

        private static void Import(Request request, Result result, List<string> warnings, bool legacy)
        {
            string roleDir = legacy ? null : ValidateDestination(request);
            if (legacy)
            {
                if (string.IsNullOrEmpty(request.path)
                    || !request.path.StartsWith("Assets/LXMaxAnimation/Library/", StringComparison.Ordinal))
                    throw new InvalidDataException("旧版导入路径无效。");
                request.kind = "model";
            }
            string fullPath = ProjectAssetPath(request.path);
            if (!string.Equals(Path.GetExtension(fullPath), ".fbx", StringComparison.OrdinalIgnoreCase)
                || !File.Exists(fullPath))
                throw new InvalidDataException("没有找到待导入的 FBX。");
            if (!string.IsNullOrEmpty(request.sha256))
            {
                using (var hasher = SHA256.Create())
                using (var file = File.OpenRead(fullPath))
                {
                    string fingerprint = BitConverter.ToString(hasher.ComputeHash(file)).Replace("-", "");
                    if (!string.Equals(fingerprint, request.sha256, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("待导入 FBX 已被其他版本替换，请重新发送当前版本。");
                }
            }
            string previousGuid = AssetDatabase.AssetPathToGUID(request.path);
            AssetDatabase.ImportAsset(request.path, ImportOptions);
            var importer = AssetImporter.GetAtPath(request.path) as ModelImporter;
            if (importer == null)
                throw new InvalidDataException("Unity 未找到此 FBX 的 ModelImporter。");

            var settings = SettingsMap(request.fbxSettings);
            importer.importAnimation = true;
            bool staticPose = request.kind == "pose" || request.kind == "tpose";
            if (staticPose)
                importer.animationCompression = ModelImporterAnimationCompression.Off;
            ApplyRig(importer, request, roleDir, settings, warnings);
            foreach (Setting field in settings.Values)
                if (!RigFields.Contains(field.name) && field.name != "materialRemaps")
                    ApplyField(importer, field, ImporterFields, warnings);
            ApplyMaterialRemaps(importer, settings, warnings);

            var requestedClips = request.clips ?? Array.Empty<Clip>();
            if (requestedClips.Length > 0 && !importer.importAnimation)
                throw new InvalidDataException("启用「导入动画」后，Unity 才能导入这些 Clip。");
            // A prior version can have animation import disabled. First reimport the
            // rig and file settings if Unity has not exposed the FBX takes yet.
            if (requestedClips.Length > 0 && importer.defaultClipAnimations.Length == 0)
            {
                importer.SaveAndReimport();
                importer = (ModelImporter)AssetImporter.GetAtPath(request.path);
            }
            if (requestedClips.Length > 0)
                ApplyClips(importer, request, requestedClips, warnings);
            else if (!legacy && request.kind == "animation" && request.clips != null)
                importer.clipAnimations = Array.Empty<ModelImporterClipAnimation>();
            importer.SaveAndReimport();

            var model = AssetDatabase.LoadAssetAtPath<GameObject>(request.path);
            if (model == null)
                throw new InvalidDataException("Unity 没有从 FBX 生成导入模型。");
            result.guid = AssetDatabase.AssetPathToGUID(request.path);
            if (string.IsNullOrEmpty(result.guid) || (!string.IsNullOrEmpty(previousGuid) && result.guid != previousGuid))
                throw new InvalidDataException("导入后资产 GUID 异常。");
            var subAssets = AssetDatabase.LoadAllAssetsAtPath(request.path);
            var clips = subAssets.OfType<AnimationClip>()
                .Where(clip => !clip.name.StartsWith("__preview__", StringComparison.OrdinalIgnoreCase)).ToArray();
            result.clipCount = clips.Length;
            if (requestedClips.Length > 0 && requestedClips.Any(clip => !clips.Any(asset => asset.name == clip.name)))
                throw new InvalidDataException("Unity 没有生成全部指定的动画片段，请查看源 Take 和帧段。");
            if (request.kind != "model" && importer.importAnimation && clips.Length == 0)
                throw new InvalidDataException("FBX 导入成功，但 Unity 未生成动画片段。请检查源 FBX 是否含关键帧。");
            if (staticPose && clips.Any(clip => AnimationUtility.GetCurveBindings(clip).Length == 0))
                throw new InvalidDataException("Unity 生成的姿态片段没有关键帧。请重新导出姿态后重试。");
            if (importer.animationType == ModelImporterAnimationType.Human)
            {
                var avatar = importer.sourceAvatar;
                if ((avatar == null || !avatar.isValid || !avatar.isHuman)
                    && !subAssets.OfType<Avatar>().Any(value => value.isValid && value.isHuman))
                    throw new InvalidDataException("Humanoid Avatar 无效。请检查角色的骨骼映射或源 Avatar。");
            }
        }

        private static string ValidateDestination(Request request)
        {
            var expectedDirectory = new Dictionary<string, string>(StringComparer.Ordinal) {
                {"model", "Model"}, {"animation", "Animations"}, {"pose", "Poses"}, {"tpose", "TPose"}
            };
            if (string.IsNullOrEmpty(request.kind) || !expectedDirectory.TryGetValue(request.kind, out string category))
                throw new InvalidDataException("Unity 资产类型无效。");
            string[] parts = (request.path ?? "").Split('/');
            if (parts.Length < 5 || parts[0] != "Assets" || parts[1] != "Charactor" || parts[3] != category)
                throw new InvalidDataException("导入路径不在对应角色的 Unity 资产目录内。");
            return AssetRoot + "/" + parts[2];
        }

        private static string ProjectAssetPath(string path)
        {
            if (string.IsNullOrEmpty(path) || !path.StartsWith("Assets/", StringComparison.Ordinal)
                || path.Contains("\\") || path.Split('/').Any(part =>
                    string.IsNullOrWhiteSpace(part) || part == "." || part == ".." || part.Contains(":")))
                throw new InvalidDataException("Unity 只接受本项目 Assets 下的资源路径或 GUID。");
            string assetDirectory = Path.GetFullPath("Assets");
            string root = assetDirectory + Path.DirectorySeparatorChar;
            string fullPath = Path.GetFullPath(path);
            if (!fullPath.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("路径超出了 Unity 资源目录。");
            for (string part = fullPath; part != null &&
                (part.StartsWith(root, StringComparison.OrdinalIgnoreCase) ||
                 part.Equals(assetDirectory, StringComparison.OrdinalIgnoreCase));
                part = Path.GetDirectoryName(part))
                if ((File.Exists(part) || Directory.Exists(part)) && (File.GetAttributes(part) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Unity 资产路径不能经过链接目录。");
            return fullPath;
        }

        private static Dictionary<string, Setting> SettingsMap(Setting[] settings)
        {
            var result = new Dictionary<string, Setting>(StringComparer.Ordinal);
            foreach (var field in settings ?? Array.Empty<Setting>())
            {
                if (field == null || string.IsNullOrEmpty(field.name) || result.ContainsKey(field.name))
                    throw new InvalidDataException("导入配置存在空白或重复字段。");
                result.Add(field.name, field);
            }
            return result;
        }

        private static readonly HashSet<string> RigFields = new HashSet<string>(new[] {
            "animationType", "avatarSetup", "sourceAvatar", "humanDescription"
        });

        private static readonly HashSet<string> ImporterFields = new HashSet<string>((
            "materialName materialSearch materialLocation globalScale importVisibility useFileUnits useFileScale " +
            "importBlendShapes importBlendShapeDeformPercent importCameras importLights addCollider normalSmoothingAngle " +
            "swapUVChannels weldVertices bakeAxisConversion optimizeBones keepQuads indexFormat preserveHierarchy " +
            "generateSecondaryUV secondaryUVAngleDistortion secondaryUVAreaDistortion secondaryUVHardAngle " +
            "secondaryUVMarginMethod secondaryUVPackMargin secondaryUVMinLightmapResolution secondaryUVMinObjectScale " +
            "generateAnimations isReadable meshOptimizationFlags optimizeMeshPolygons optimizeMeshVertices skinWeights " +
            "maxBonesPerVertex minBoneWeight importNormals normalSmoothingSource importBlendShapeNormals " +
            "normalCalculationMode importTangents bakeIK resampleCurves removeConstantScaleCurves strictVertexDataChecks " +
            "meshCompression importAnimation optimizeGameObjects extraExposedTransformPaths extraUserProperties " +
            "animationCompression importAnimatedCustomProperties importConstraints aCLCompressionLevel aCLCurvePrecision " +
            "animationRotationError animationPositionError animationScaleError animationWrapMode humanoidOversampling " +
            "motionNodeName useSRGBMaterialColor sortHierarchyByName materialImportMode autoGenerateAvatarMappingIfUnspecified " +
            "isVirtualGeometry").Split(' '));

        private static readonly HashSet<string> ClipFields = new HashSet<string>((
            "wrapMode loop rotationOffset heightOffset cycleOffset additiveType basePoseType additiveSelectedAnimation " +
            "additiveSelectedAnimationFrameIndex loopTime lockToRoot loopPose lockRootRotation lockRootHeightY " +
            "lockRootPositionXZ keepOriginalOrientation keepOriginalPositionY keepOriginalPositionXZ heightFromFeet " +
            "mirror maskType maskSource intervals additiveReferencePoseFrame hasAdditiveReferencePose").Split(' '));

        private static T ReadValue<T>(string json)
        {
            if (string.IsNullOrEmpty(json))
                throw new InvalidDataException("空的 JSON 配置值。");
            return JsonUtility.FromJson<ValueBox<T>>("{\"value\":" + json + "}").value;
        }

        private static object ReadValue(Type type, string json)
        {
            if (type.IsEnum)
                return Enum.Parse(type, ReadValue<string>(json), true);
            if (typeof(Object).IsAssignableFrom(type))
                return ResolveAsset(ReadValue<string>(json), type);
            var boxType = typeof(ValueBox<>).MakeGenericType(type);
            return boxType.GetField("value").GetValue(JsonUtility.FromJson("{\"value\":" + json + "}", boxType));
        }

        private static void ApplyField(object target, Setting setting, HashSet<string> allowed, List<string> warnings)
        {
            if (setting.name == "extensions")
                return;
            var field = allowed.Contains(setting.name)
                ? target.GetType().GetProperty(setting.name, BindingFlags.Public | BindingFlags.Instance) : null;
            if (field == null || !field.CanWrite || field.GetSetMethod() == null)
            {
                warnings.Add("当前编辑器不支持导入选项 " + setting.name);
                return;
            }
            try
            {
                field.SetValue(target, ReadValue(field.PropertyType, setting.json));
            }
            catch (Exception error)
            {
                warnings.Add(setting.name + " 未应用：" + (error.InnerException ?? error).Message);
            }
        }

        private static Object ResolveAsset(string reference, Type type)
        {
            if (string.IsNullOrWhiteSpace(reference))
                return null;
            string path = reference;
            if (Guid.TryParseExact(reference, "N", out _))
                path = AssetDatabase.GUIDToAssetPath(reference);
            ProjectAssetPath(path);
            var matches = AssetDatabase.LoadAllAssetsAtPath(path).Where(type.IsInstanceOfType).ToArray();
            if (matches.Length != 1)
                throw new InvalidDataException("资源未找到或在同一文件内存在多个匹配项：" + reference);
            return matches[0];
        }

        private static void ApplyRig(ModelImporter importer, Request request, string roleDir,
                                     Dictionary<string, Setting> settings, List<string> warnings)
        {
            string animationType = settings.TryGetValue("animationType", out Setting type)
                ? ReadValue<string>(type.json) : request.rig;
            if (string.IsNullOrWhiteSpace(animationType))
                animationType = "Generic";
            if (string.Equals(animationType, "Humanoid", StringComparison.OrdinalIgnoreCase))
                animationType = "Human";
            if (!Enum.TryParse(animationType, true, out ModelImporterAnimationType rig) || !Enum.IsDefined(typeof(ModelImporterAnimationType), rig))
                throw new InvalidDataException("Unity 骨骼类型无效：" + animationType);
            importer.animationType = rig;
            if (rig != ModelImporterAnimationType.Generic && rig != ModelImporterAnimationType.Human)
                return;

            Avatar avatar = null;
            bool explicitAvatar = settings.TryGetValue("sourceAvatar", out Setting reference);
            if (explicitAvatar)
                avatar = (Avatar)ResolveAsset(ReadValue<string>(reference.json), typeof(Avatar));
            else if (request.kind != "model" && roleDir != null && !settings.ContainsKey("avatarSetup"))
                avatar = FindRoleAvatar(roleDir, rig == ModelImporterAnimationType.Human);
            if (avatar != null && (!avatar.isValid || (rig == ModelImporterAnimationType.Human && !avatar.isHuman)))
                throw new InvalidDataException("指定的 Avatar 与当前 Unity 骨骼类型不匹配。");

            ModelImporterAvatarSetup setup = avatar != null ? ModelImporterAvatarSetup.CopyFromOther
                : ModelImporterAvatarSetup.CreateFromThisModel;
            if (settings.TryGetValue("avatarSetup", out Setting setupField))
                setup = (ModelImporterAvatarSetup)ReadValue(typeof(ModelImporterAvatarSetup), setupField.json);
            if (setup == ModelImporterAvatarSetup.CopyFromOther && avatar == null && roleDir != null)
                avatar = FindRoleAvatar(roleDir, rig == ModelImporterAnimationType.Human);
            if (setup == ModelImporterAvatarSetup.CopyFromOther && avatar == null)
                throw new InvalidDataException("请指定有效的源 Avatar，或先导入同一角色唯一的 Model。");
            importer.avatarSetup = setup;
            if (setup == ModelImporterAvatarSetup.CopyFromOther)
                importer.sourceAvatar = avatar;
            if (settings.TryGetValue("humanDescription", out Setting human) && human.json != "{}")
                ApplyField(importer, human, RigFields, warnings);
        }

        private static Avatar FindRoleAvatar(string directory, bool human)
        {
            string modelFolder = directory + "/Model";
            if (!AssetDatabase.IsValidFolder(modelFolder))
                return null;
            ProjectAssetPath(modelFolder);
            var avatars = AssetDatabase.FindAssets("t:Model", new[] { modelFolder })
                .Select(AssetDatabase.GUIDToAssetPath).Distinct()
                .SelectMany(AssetDatabase.LoadAllAssetsAtPath).OfType<Avatar>()
                .Where(avatar => avatar.isValid && avatar.isHuman == human).ToArray();
            return avatars.Length == 1 ? avatars[0] : null;
        }

        private static void ApplyMaterialRemaps(ModelImporter importer, Dictionary<string, Setting> settings,
                                                List<string> warnings)
        {
            if (!settings.TryGetValue("materialRemaps", out Setting materialSetting))
                return;
            foreach (var remap in ReadValue<MaterialRemap[]>(materialSetting.json) ?? Array.Empty<MaterialRemap>())
            {
                try
                {
                    if (string.IsNullOrWhiteSpace(remap.sourceName) ||
                        !string.IsNullOrEmpty(remap.type) && remap.type != "Material" && remap.type != "UnityEngine.Material")
                        throw new InvalidDataException("材质名称或类型无效。");
                    var target = ResolveAsset(string.IsNullOrEmpty(remap.targetGuid) ? remap.targetPath : remap.targetGuid,
                                              typeof(Material));
                    if (target == null)
                        throw new InvalidDataException("尚未选择材质资源。");
                    importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), remap.sourceName), target);
                }
                catch (Exception error)
                {
                    warnings.Add("材质重映射未应用：" + error.Message);
                }
            }
        }

        private static bool Finite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        private static void ApplyClips(ModelImporter importer, Request request, Clip[] clips, List<string> warnings)
        {
            var takes = importer.defaultClipAnimations;
            if (takes.Length == 0)
                throw new InvalidDataException("FBX 内没有可导入的动画 Take。");
            var configured = new List<ModelImporterClipAnimation>();
            var masks = new Dictionary<int, MaskEntry[]>();
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var clip in clips)
            {
                if (clip == null || string.IsNullOrWhiteSpace(clip.name) || !names.Add(clip.name)
                    || !Finite(clip.firstFrame) || !Finite(clip.lastFrame) || clip.lastFrame < clip.firstFrame)
                    throw new InvalidDataException("片段名称或帧段无效，片段名称不能重复。");
                var take = takes.FirstOrDefault(value =>
                    string.Equals(value.takeName, clip.takeName, StringComparison.Ordinal));
                if (take == null && takes.Length == 1)
                {
                    take = takes[0];
                    if (!string.IsNullOrEmpty(clip.takeName))
                        warnings.Add(clip.name + " 使用 FBX 中唯一的 Take " + take.takeName);
                }
                if (take == null)
                    throw new InvalidDataException("找不到动画片段 " + clip.name + " 的源 Take。");
                float first = take.firstFrame + clip.firstFrame - request.sourceStart;
                float last = take.firstFrame + clip.lastFrame - request.sourceStart;
                if (first < take.firstFrame - 0.01f || last > take.lastFrame + 0.01f)
                    throw new InvalidDataException("片段超出 FBX Take 的范围：" + clip.name);
                var imported = new ModelImporterClipAnimation {
                    name = clip.name, takeName = take.takeName,
                    firstFrame = Mathf.Max(take.firstFrame, first), lastFrame = Mathf.Min(take.lastFrame, last)
                };
                foreach (var setting in SettingsMap(clip.settings).Values)
                {
                    if (setting.name == "events")
                        imported.events = BuildEvents(clip, ReadValue<EventSetting[]>(setting.json), warnings);
                    else if (setting.name == "curves")
                        imported.curves = BuildCurves(ReadValue<CurveSetting[]>(setting.json));
                    else if (setting.name == "transformMask")
                        masks[configured.Count] = ReadValue<MaskEntry[]>(setting.json);
                    else
                        ApplyField(imported, setting, ClipFields, warnings);
                }
                configured.Add(imported);
            }
            importer.clipAnimations = configured.ToArray();
            ApplyMasks(importer, masks, warnings);
        }

        private static AnimationEvent[] BuildEvents(Clip clip, EventSetting[] events, List<string> warnings)
        {
            var result = new List<AnimationEvent>();
            foreach (var item in events ?? Array.Empty<EventSetting>())
            {
                if (item == null || string.IsNullOrWhiteSpace(item.function) || !Finite(item.frame) ||
                    item.frame < clip.firstFrame || item.frame > clip.lastFrame)
                {
                    warnings.Add(clip.name + " 有事件超出片段范围或未填写函数名。");
                    continue;
                }
                var value = new AnimationEvent {
                    functionName = item.function, stringParameter = item.stringParameter,
                    intParameter = item.intParameter, floatParameter = item.floatParameter,
                    time = clip.lastFrame > clip.firstFrame
                        ? (item.frame - clip.firstFrame) / (clip.lastFrame - clip.firstFrame) : 0
                };
                try { value.objectReferenceParameter = ResolveAsset(item.objectReference, typeof(Object)); }
                catch (Exception error) { warnings.Add(clip.name + " 的事件引用未应用：" + error.Message); }
                result.Add(value);
            }
            return result.ToArray();
        }

        private static ClipAnimationInfoCurve[] BuildCurves(CurveSetting[] curves)
        {
            return (curves ?? Array.Empty<CurveSetting>()).Select(item => new ClipAnimationInfoCurve {
                name = item.name,
                curve = new AnimationCurve((item.curve?.keys ?? Array.Empty<CurveKey>()).Select(key =>
                    new Keyframe(key.time, key.value, key.inTangent, key.outTangent, key.inWeight, key.outWeight)
                    { weightedMode = (WeightedMode)key.weightedMode }).ToArray())
            }).ToArray();
        }

        private static void ApplyMasks(ModelImporter importer, Dictionary<int, MaskEntry[]> masks, List<string> warnings)
        {
            if (masks.Count == 0)
                return;
            var serialized = new SerializedObject(importer);
            var clips = serialized.FindProperty("m_ClipAnimations");
            foreach (var entry in masks)
            {
                if (entry.Value == null || entry.Value.Length == 0)
                    continue;
                var mask = clips?.GetArrayElementAtIndex(entry.Key).FindPropertyRelative("transformMask");
                if (mask == null || !mask.isArray)
                {
                    warnings.Add("当前编辑器不支持直接导入变换遮罩。");
                    continue;
                }
                mask.arraySize = entry.Value.Length;
                for (int index = 0; index < entry.Value.Length; index++)
                {
                    var element = mask.GetArrayElementAtIndex(index);
                    element.FindPropertyRelative("m_Path").stringValue = entry.Value[index].path ?? "";
                    element.FindPropertyRelative("m_Weight").floatValue = entry.Value[index].active ? 1f : 0f;
                }
            }
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }
    }
}
