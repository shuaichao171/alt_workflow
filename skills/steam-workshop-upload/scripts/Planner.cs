using System.Text.RegularExpressions;

namespace KleiWorkshopUploader;

internal static class Planner
{
    internal static UploadPlan Create(JobContext context)
    {
        var plan = new UploadPlan
        {
            ConfigSha256 = JobContext.Hash(context.ConfigPath),
            SourceDirectory = context.SourceRoot
        };
        string modinfo = Path.Combine(context.SourceRoot, "modinfo.lua");
        string lua = File.ReadAllText(modinfo);
        string literalVersion = ModInfo.ReadLuaField(lua, "version").Trim();
        if (!string.IsNullOrWhiteSpace(context.Job.Version) && literalVersion.Length > 0 && context.Job.Version.Trim() != literalVersion)
            throw new ArgumentException("任务 version 与 modinfo.lua 的字面版本不一致，请修正后重新 plan。");
        plan.Version = string.IsNullOrWhiteSpace(context.Job.Version) ? literalVersion : context.Job.Version.Trim();
        plan.VersionCompatible = string.IsNullOrWhiteSpace(context.Job.VersionCompatible)
            ? ModInfo.ReadLuaField(lua, "version_compatible").Trim() : context.Job.VersionCompatible.Trim();
        plan.ReferenceFiles.Add(JobContext.Digest(modinfo, modinfo));
        if (context.Job.UpdatePreview) AddReference(plan, context.Resolve(context.Job.PreviewFile));
        if (context.Job.UpdateMetadata && !string.IsNullOrWhiteSpace(context.Job.DescriptionFile))
            AddReference(plan, context.Resolve(context.Job.DescriptionFile));

        if (context.Job.UpdateContent)
        {
            plan.SourceFiles = SelectFiles(context, plan.Skipped);
            if (!plan.SourceFiles.Any(f => f.Path.Equals("modinfo.lua", StringComparison.OrdinalIgnoreCase)))
                throw new ArgumentException("文件规则必须保留根目录 modinfo.lua。");
            if (string.IsNullOrWhiteSpace(plan.Version))
                throw new ArgumentException("无法静态读取 modinfo.lua version；动态版本请显式填写任务 version。");
            plan.PayloadDirectory = Path.Combine(context.Workspace, "payload_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(plan.PayloadDirectory);
            foreach (FileDigest file in plan.SourceFiles)
            {
                string source = Path.Combine(context.SourceRoot, file.Path);
                string target = Path.Combine(plan.PayloadDirectory, file.Path);
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                File.Copy(source, target);
                File.SetLastWriteTimeUtc(target, File.GetLastWriteTimeUtc(source));
                if (JobContext.Hash(target) != file.Sha256) throw new IOException("生成快照时文件发生变化：" + file.Path);
            }
            if (context.Job.AppId == 322330) SteamworksWorkshopUploader.WriteDstModManifest(plan.PayloadDirectory);
            plan.Files = Inventory(plan.PayloadDirectory);
        }
        JobContext.WriteJson(context.PlanPath, plan);
        Console.WriteLine($"计划：{context.Job.Operation} / AppID={context.Job.AppId} / WorkshopID={context.Job.WorkshopId}");
        foreach (FileDigest file in plan.Files) Console.WriteLine($"  + {file.Path} ({file.Bytes} bytes)");
        foreach (SkippedFile file in plan.Skipped) Console.WriteLine($"  - {file.Path} [{file.Reason}]");
        Console.WriteLine($"共 {plan.Files.Count} 个上传文件，{plan.Files.Sum(f => f.Bytes)} bytes；version={plan.Version}");
        Console.WriteLine("计划已写入：" + context.PlanPath);
        return plan;
    }

    internal static UploadPlan Check(JobContext context)
    {
        if (!File.Exists(context.PlanPath)) throw new ArgumentException("请先执行 plan。");
        var plan = System.Text.Json.JsonSerializer.Deserialize<UploadPlan>(File.ReadAllText(context.PlanPath), JobContext.JsonOptions)
            ?? throw new ArgumentException("上传计划为空。");
        if (plan.SchemaVersion != 1 || plan.ConfigSha256 != JobContext.Hash(context.ConfigPath) || !JobContext.SamePath(plan.SourceDirectory, context.SourceRoot))
            throw new InvalidOperationException("任务配置已变化，请重新 plan。");
        foreach (FileDigest reference in plan.ReferenceFiles)
            if (!File.Exists(reference.Path) || JobContext.Hash(reference.Path) != reference.Sha256)
                throw new InvalidOperationException("引用文件已变化，请重新 plan：" + reference.Path);
        if (context.Job.UpdateContent)
        {
            List<FileDigest> current = SelectFiles(context, []);
            if (!current.SequenceEqual(plan.SourceFiles)) throw new InvalidOperationException("选中的源文件已变化，请重新 plan。");
            string payloadPrefix = Path.GetFullPath(context.Workspace).TrimEnd('\\', '/') + Path.DirectorySeparatorChar;
            if (string.IsNullOrWhiteSpace(plan.PayloadDirectory) || !Path.GetFullPath(plan.PayloadDirectory).StartsWith(payloadPrefix, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("计划的快照路径不在当前任务工作目录中。");
            if (!Inventory(plan.PayloadDirectory).SequenceEqual(plan.Files))
                throw new InvalidOperationException("上传快照已变化，请重新 plan。");
        }
        Console.WriteLine("计划检查通过：配置、源文件、快照和引用文件均一致。");
        return plan;
    }

    private static void AddReference(UploadPlan plan, string path)
    {
        if (!File.Exists(path)) throw new FileNotFoundException("引用文件不存在。", path);
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new ArgumentException("引用文件不能是符号链接：" + path);
        plan.ReferenceFiles.Add(JobContext.Digest(path, path));
    }

    private static List<FileDigest> SelectFiles(JobContext context, List<SkippedFile> skipped)
    {
        Regex[] include = context.Job.Include.Select(Glob).ToArray();
        Regex[] exclude = context.Job.Exclude.Select(Glob).ToArray();
        var selected = new List<FileDigest>();
        Walk(context.SourceRoot);
        return selected.OrderBy(f => f.Path, StringComparer.OrdinalIgnoreCase).ToList();

        void Walk(string directory)
        {
            foreach (string path in Directory.GetFileSystemEntries(directory).Order(StringComparer.OrdinalIgnoreCase))
            {
                string relative = Path.GetRelativePath(context.SourceRoot, path).Replace('\\', '/');
                FileAttributes attributes = File.GetAttributes(path);
                bool isDirectory = (attributes & FileAttributes.Directory) != 0;
                string reason = "";
                if ((attributes & FileAttributes.ReparsePoint) != 0) reason = "符号链接/目录联接";
                else if (Path.GetFileName(path).StartsWith('.')) reason = "官方规则：点开头的名称";
                else if (isDirectory && (Path.GetFileName(path) == "_ai_work" || JobContext.SamePath(path, context.JobDirectory))) reason = "任务产物目录";
                else if (exclude.Any(r => r.IsMatch(relative) || isDirectory && r.IsMatch(relative + "/"))) reason = "exclude";
                else if (!isDirectory && !include.Any(r => r.IsMatch(relative))) reason = "未匹配 include";
                else if (!isDirectory && SteamworksWorkshopUploader.ShouldSkipUploadFile(new FileInfo(path), context.Job.UploadRedundantFiles, context.SourceRoot, context.Job.AppId == 322330)) reason = "官方文件过滤/生成的 manifest";
                if (reason.Length > 0) skipped.Add(new(relative + (isDirectory ? "/" : ""), reason));
                else if (isDirectory) Walk(path);
                else selected.Add(JobContext.Digest(path, relative));
            }
        }
    }

    internal static List<FileDigest> Inventory(string directory)
    {
        if (!Directory.Exists(directory)) throw new DirectoryNotFoundException("上传快照不存在。");
        var files = new List<FileDigest>();
        Walk(directory);
        return files.OrderBy(f => f.Path, StringComparer.OrdinalIgnoreCase).ToList();
        void Walk(string current)
        {
            foreach (string path in Directory.GetFileSystemEntries(current))
            {
                var attributes = File.GetAttributes(path);
                if ((attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("上传快照中出现链接：" + path);
                if ((attributes & FileAttributes.Directory) != 0) Walk(path);
                else files.Add(JobContext.Digest(path, Path.GetRelativePath(directory, path).Replace('\\', '/')));
            }
        }
    }

    private static Regex Glob(string pattern)
    {
        if (string.IsNullOrWhiteSpace(pattern)) throw new ArgumentException("文件规则不能为空。");
        pattern = pattern.Replace('\\', '/');
        if (pattern.StartsWith('/') || pattern.Contains(':') || pattern.Split('/').Any(part => part is ".." or "."))
            throw new ArgumentException("文件规则必须是相对于模组根目录的路径：" + pattern);
        string regex = "^";
        for (int i = 0; i < pattern.Length; i++)
        {
            if (pattern[i] == '*' && i + 1 < pattern.Length && pattern[i + 1] == '*')
            {
                i++;
                if (i + 1 < pattern.Length && pattern[i + 1] == '/') { regex += "(?:.*/)?"; i++; }
                else regex += ".*";
            }
            else if (pattern[i] == '*') regex += "[^/]*";
            else if (pattern[i] == '?') regex += "[^/]";
            else regex += Regex.Escape(pattern[i].ToString());
        }
        return new Regex(regex + "$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromSeconds(2));
    }
}
