using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace KleiWorkshopUploader;

internal sealed class UploadJob
{
    public string Operation { get; set; } = "update";
    public uint AppId { get; set; } = 322330;
    public string WorkshopId { get; set; } = "0";
    public string TargetSource { get; set; } = "user";
    public TargetConfirmation TargetConfirmation { get; set; }
    public string SourceDirectory { get; set; } = "";
    public string[] Include { get; set; } = ["**"];
    public string[] Exclude { get; set; } = [];
    public bool UploadRedundantFiles { get; set; }
    public bool UpdateContent { get; set; } = true;
    public bool UpdatePreview { get; set; }
    public bool UpdateMetadata { get; set; }
    public bool UpdateTags { get; set; }
    public bool UpdateVersionMetadata { get; set; } = true;
    public string PreviewFile { get; set; } = "";
    public string Title { get; set; } = "";
    public string Description { get; set; } = "";
    public string DescriptionFile { get; set; } = "";
    public string[] Tags { get; set; }
    public string Version { get; set; } = "";
    public string VersionCompatible { get; set; } = "";
    public string ChangeNote { get; set; } = "";
    public int? Visibility { get; set; }
    public bool Force { get; set; }
}

internal sealed class TargetConfirmation
{
    public string Decision { get; set; } = "pending";
    public uint AppId { get; set; }
    public string WorkshopId { get; set; } = "";
    public string UserReply { get; set; } = "";
}

internal sealed class TargetConfirmationRequired(string message) : Exception(message);

internal sealed record FileDigest(string Path, long Bytes, string Sha256);
internal sealed record SkippedFile(string Path, string Reason);

internal sealed class UploadPlan
{
    public int SchemaVersion { get; set; } = 1;
    public DateTime CreatedUtc { get; set; } = DateTime.UtcNow;
    public string ConfigSha256 { get; set; }
    public string SourceDirectory { get; set; }
    public string PayloadDirectory { get; set; }
    public string Version { get; set; }
    public string VersionCompatible { get; set; }
    public List<FileDigest> SourceFiles { get; set; } = [];
    public List<FileDigest> Files { get; set; } = [];
    public List<FileDigest> ReferenceFiles { get; set; } = [];
    public List<SkippedFile> Skipped { get; set; } = [];
}

internal sealed class JobContext
{
    internal static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
    };

    internal readonly UploadJob Job;
    internal readonly string ConfigPath, JobDirectory, SourceRoot, PlanPath, ResultPath;
    internal string Workspace => Path.ChangeExtension(ConfigPath, ".workshop");
    internal ulong PublishedId => ulong.Parse(Job.WorkshopId);

    internal JobContext(string configPath)
    {
        ConfigPath = Path.GetFullPath(configPath);
        JobDirectory = Path.GetDirectoryName(ConfigPath);
        Job = JsonSerializer.Deserialize<UploadJob>(File.ReadAllText(ConfigPath), JsonOptions)
            ?? throw new InvalidOperationException("任务 JSON 为空。");
        if (Job.AppId is not (219740 or 322330)) throw new ArgumentException("app_id 只能是 219740（单机）或 322330（联机）。");
        if (Job.Operation is not ("update" or "create")) throw new ArgumentException("operation 只能是 update 或 create。");
        if (Job.TargetSource is not ("user" or "list")) throw new ArgumentException("target_source 只能是 user 或 list。");
        if (Job.Operation == "create" && Job.TargetSource == "list") throw new ArgumentException("列表候选只能用于 update，不能擅自新建物品。");
        if (!ulong.TryParse(Job.WorkshopId, out ulong id) || (Job.Operation == "update" ? id == 0 : id != 0))
            throw new ArgumentException("update 必须提供非零字符串 workshop_id；create 的 workshop_id 必须是字符串 0。");
        if (string.IsNullOrWhiteSpace(Job.SourceDirectory)) throw new ArgumentException("缺少 source_directory。");
        SourceRoot = Resolve(Job.SourceDirectory);
        if (!Directory.Exists(SourceRoot)) throw new DirectoryNotFoundException("模组目录不存在：" + SourceRoot);
        if ((File.GetAttributes(SourceRoot) & FileAttributes.ReparsePoint) != 0)
            throw new ArgumentException("请使用模组的实际目录，不要使用符号链接或目录联接。");
        if (SamePath(SourceRoot, JobDirectory)) throw new ArgumentException("任务 JSON 应放在 _ai_work/workshop/ 等独立子目录。");
        if (!File.Exists(Path.Combine(SourceRoot, "modinfo.lua"))) throw new ArgumentException("模组根目录缺少 modinfo.lua。");
        if (Job.Visibility is < 0 or > 3) throw new ArgumentException("visibility 必须为 0、1、2 或 3。");
        if (Job.Include == null || Job.Exclude == null || Job.Include.Length == 0)
            throw new ArgumentException("include 必须是非空数组，exclude 必须是数组。");
        if (!Job.UpdateContent && !Job.UpdatePreview && !Job.UpdateMetadata && !Job.UpdateTags)
            throw new ArgumentException("必须启用至少一个更新项。");
        if (Job.UpdateTags && Job.Tags == null) throw new ArgumentException("update_tags=true 时必须显式提供 tags 数组。");
        if (!string.IsNullOrEmpty(Job.DescriptionFile) && !string.IsNullOrEmpty(Job.Description))
            throw new ArgumentException("description 和 description_file 只能指定一个。");
        if (Job.Operation == "create" && (!Job.UpdateContent || !Job.UpdatePreview || !Job.UpdateMetadata))
            throw new ArgumentException("创建物品必须启用 update_content、update_preview、update_metadata。");
        if (Job.UpdateMetadata && string.IsNullOrWhiteSpace(Job.Title))
            throw new ArgumentException("更新标题简介或新建物品必须显式填写 title。");
        if (Job.UpdatePreview)
        {
            string preview = Resolve(Job.PreviewFile);
            if (string.IsNullOrWhiteSpace(Job.PreviewFile) || !File.Exists(preview)) throw new ArgumentException("preview_file 不存在。");
            if (new FileInfo(preview).Length > 1024 * 1024) throw new ArgumentException("Steam 预览图超过 1 MiB，请先压缩。");
        }
        PlanPath = Path.ChangeExtension(ConfigPath, ".plan.json");
        ResultPath = Path.ChangeExtension(ConfigPath, ".result.json");
    }

    internal string Resolve(string path) => Path.GetFullPath(Path.Combine(JobDirectory, path));
    internal void RequireConfirmedTarget()
    {
        if (Job.TargetSource != "list") return;
        TargetConfirmation confirmation = Job.TargetConfirmation;
        if (confirmation == null || confirmation.Decision != "confirmed" || confirmation.AppId != Job.AppId || confirmation.WorkshopId != Job.WorkshopId || string.IsNullOrWhiteSpace(confirmation.UserReply))
            throw new TargetConfirmationRequired("从列表匹配的 ID 必须先向用户展示名称、游戏、ID、链接并获得确切答复。缺少匹配的 target_confirmation；不得上传，force 不能跳过。");
    }
    internal static bool SamePath(string a, string b) => string.Equals(Path.GetFullPath(a).TrimEnd('\\', '/'), Path.GetFullPath(b).TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase);
    internal static string Hash(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream));
    }
    internal static FileDigest Digest(string absolutePath, string label) => new(label, new FileInfo(absolutePath).Length, Hash(absolutePath));
    internal static void WriteJson<T>(string path, T value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        string temporaryPath = path + ".tmp";
        File.WriteAllText(temporaryPath, JsonSerializer.Serialize(value, JsonOptions), new UTF8Encoding(false));
        File.Move(temporaryPath, path, true);
    }
}
