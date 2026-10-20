// Shared fixed-package verification for the UI and stable launcher.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace BgvSceneControl
{
    internal static class Files
    {
        internal const string Runtime = @"E:\Github\Building-Generation-Validation\.runtime";
        internal const string Owner = "BGV.Windows.SceneControl.Desktop.v1";
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 2097152, RecursionLimit = 64 };
        internal static string Safe(string name)
        {
            var path = Path.GetFullPath(name);
            string part = path;
            while (!String.IsNullOrEmpty(part))
            {
                if ((File.Exists(part) || Directory.Exists(part)) && (File.GetAttributes(part) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("REPARSE_PATH");
                var parent = Path.GetDirectoryName(part);
                if (parent == part) break;
                part = parent;
            }
            return path;
        }
        internal static string Hash(byte[] bytes)
        {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }
        internal static string HashFile(string path)
        {
            var info = new FileInfo(Safe(path));
            if (info.Length > 67108864) throw new InvalidDataException("PACKAGE_FILE_TOO_LARGE");
            using (var sha = SHA256.Create()) using (var stream = File.OpenRead(info.FullName))
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
        internal static Dictionary<string, object> Read(string path)
        {
            var file = new FileInfo(Safe(path));
            if (file.Length > 2097152) throw new InvalidDataException("METADATA_TOO_LARGE");
            var result = Json.DeserializeObject(File.ReadAllText(file.FullName, Encoding.UTF8)) as Dictionary<string, object>;
            if (result == null) throw new InvalidDataException("INVALID_METADATA");
            return result;
        }
        internal static void Save(string path, object value)
        {
            path = Safe(path); var directory = Safe(Path.GetDirectoryName(path));
            Directory.CreateDirectory(directory); Safe(directory);
            var temporary = Safe(path + ".tmp");
            File.WriteAllText(temporary, Json.Serialize(value), new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
        }
        private static void Inventory(string directory, string root, HashSet<string> found)
        {
            Safe(directory);
            foreach (var child in Directory.GetFileSystemEntries(directory))
            {
                Safe(child);
                if (Directory.Exists(child)) Inventory(child, root, found);
                else
                {
                    var relative = child.Substring(root.Length + 1).Replace('\\', '/');
                    if (relative != "manifest.json") found.Add(relative);
                }
            }
        }
        internal static string VerifyPackage(out string source)
        {
            var executable = Safe(Assembly.GetExecutingAssembly().Location);
            var app = Path.GetDirectoryName(executable); var root = Safe(Path.GetDirectoryName(app));
            return VerifySnapshot(root, out source);
        }
        internal static string VerifySnapshot(string root, out string source)
        {
            root = Safe(root);
            var app = Safe(Path.Combine(root, "app"));
            var sha = Path.GetFileName(root);
            if (!Regex.IsMatch(sha, "^[0-9a-f]{64}$") || Path.GetFileName(app) != "app" ||
                !String.Equals(root, Path.Combine(Runtime, "desktop", "snapshots", sha), StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("PACKAGE_LOCATION_INVALID");
            var record = Read(Path.Combine(root, "manifest.json"));
            if (!record.ContainsKey("owner") || !Object.Equals(record["owner"], Owner) || !record.ContainsKey("sha256") || !Object.Equals(record["sha256"], sha))
                throw new InvalidDataException("PACKAGE_IDENTITY_INVALID");
            var files = record.ContainsKey("files") ? record["files"] as Dictionary<string, object> : null;
            if (files == null || files.Count == 0 || files.Count > 512) throw new InvalidDataException("PACKAGE_FILESET_INVALID");
            var ordered = new SortedDictionary<string, string>(StringComparer.Ordinal);
            var aliases = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var item in files)
            {
                var name = item.Key; var hash = item.Value as string;
                if (!Regex.IsMatch(name, @"^[A-Za-z0-9_./ -]{1,240}$") || name.StartsWith("/", StringComparison.Ordinal) ||
                    name.Split('/').Any(p => p.Length == 0 || p == "." || p == ".." || p.EndsWith(".", StringComparison.Ordinal) || p.EndsWith(" ", StringComparison.Ordinal)) ||
                    name == "manifest.json" || hash == null || !Regex.IsMatch(hash, "^[0-9a-f]{64}$") || !aliases.Add(name))
                    throw new InvalidDataException("PACKAGE_PATH_INVALID");
                ordered.Add(name, hash);
            }
            var canonical = "{" + String.Join(",", ordered.Select(p => "\"" + p.Key + "\":\"" + p.Value + "\"")) + "}";
            if (Hash(Encoding.UTF8.GetBytes(canonical)) != sha) throw new InvalidDataException("PACKAGE_MANIFEST_CHANGED");
            var found = new HashSet<string>(StringComparer.Ordinal); Inventory(root, root, found);
            if (!found.SetEquals(ordered.Keys) || !ordered.ContainsKey("app/SceneControl.exe") || !ordered.ContainsKey("source/desktop.py"))
                throw new InvalidDataException("PACKAGE_EXTRA_OR_MISSING_FILE");
            foreach (var item in ordered)
                if (HashFile(Path.Combine(root, item.Key.Replace('/', Path.DirectorySeparatorChar))) != item.Value)
                    throw new InvalidDataException("PACKAGE_CONTENT_CHANGED");
            source = Safe(Path.Combine(root, "source")); return sha;
        }
    }

}
