using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
public static class SchemaExport {
 [Serializable] public class Field { public string name,type,defaultJson; public string[] options; }
 [Serializable] public class Schema { public string version; public Field[] importer,clip; public string[] readOnly,obsolete; }
 static string Value(object value,Type type) {
  if(value==null)return typeof(UnityEngine.Object).IsAssignableFrom(type)?"\"\"":type.IsArray?"[]":"null";
  if(type.IsEnum || type==typeof(string))return "\""+value.ToString().Replace("\\","\\\\").Replace("\"","\\\"")+"\"";
  if(type==typeof(bool))return (bool)value?"true":"false";
  if(type.IsPrimitive)return Convert.ToString(value,System.Globalization.CultureInfo.InvariantCulture);
  if(type.IsArray)return "[]";
  if(typeof(UnityEngine.Object).IsAssignableFrom(type))return "\"\"";
  return JsonUtility.ToJson(value);
 }
 static PropertyInfo[] Props(Type type)=>type.GetProperties(BindingFlags.Public|BindingFlags.Instance|BindingFlags.DeclaredOnly);
 static Field[] Fields(Type type,object obj)=>Props(type).Where(p=>p.CanRead&&p.GetSetMethod()!=null&&!p.IsDefined(typeof(ObsoleteAttribute),true)&&p.Name!="clipAnimations").Select(p=>{
  object value=null;try{value=p.GetValue(obj);}catch{}
  return new Field{name=p.Name,type=p.PropertyType.FullName,options=p.PropertyType.IsEnum?Enum.GetNames(p.PropertyType):null,defaultJson=Value(value,p.PropertyType)};
 }).ToArray();
 public static void Run(){
  AssetDatabase.ImportAsset("Assets/sample.fbx",ImportAssetOptions.ForceSynchronousImport);
  var importer=AssetImporter.GetAtPath("Assets/sample.fbx") as ModelImporter;
  if(importer==null)throw new Exception("Missing FBX importer");
  var schema=new Schema{version=Application.unityVersion,importer=Fields(typeof(ModelImporter),importer),clip=Fields(typeof(ModelImporterClipAnimation),new ModelImporterClipAnimation()),readOnly=Props(typeof(ModelImporter)).Where(p=>p.GetSetMethod()==null).Select(p=>p.Name).ToArray(),obsolete=Props(typeof(ModelImporter)).Where(p=>p.IsDefined(typeof(ObsoleteAttribute),true)).Select(p=>p.Name).ToArray()};
  File.WriteAllText(Path.GetFullPath("../../ui/unity-schema.json"),JsonUtility.ToJson(schema,true));
  Debug.Log("SCHEMA_EXPORTED "+schema.importer.Length+" / "+schema.clip.Length);
 }
}
