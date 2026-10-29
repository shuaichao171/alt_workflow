using System.Text;
using System.Text.Json;

namespace KleiWorkshopUploader;

internal sealed class PublishedListQuery
{
    public uint AppId { get; set; } = 322330;
    public string SearchName { get; set; } = "";
}

internal static class PublishedList
{
    internal static void Run(string configPath)
    {
        var query = JsonSerializer.Deserialize<PublishedListQuery>(File.ReadAllText(configPath), JobContext.JsonOptions)
            ?? throw new ArgumentException("列表查询 JSON 为空。");
        if (query.AppId is not (219740 or 322330)) throw new ArgumentException("app_id 只能是 219740 或 322330。");
        var uploader = new SteamworksWorkshopUploader(AppContext.BaseDirectory);
        List<WorkshopPublishedItem> items = uploader.ListPublishedItems(query.AppId,
            message => Console.WriteLine($"[{DateTimeOffset.Now:HH:mm:ss}] {message}"));
        var resultItems = items.Select(item => new
        {
            WorkshopId = item.PublishedFileId.ToString(),
            item.AppId,
            OwnerSteamId = item.OwnerSteamId.ToString(),
            item.Title,
            item.TitleChinese,
            item.TitleEnglish,
            item.Version,
            item.Visibility,
            item.TimeUpdated,
            UpdatedUtc = item.TimeUpdated == 0 ? (DateTimeOffset?)null : DateTimeOffset.FromUnixTimeSeconds(item.TimeUpdated),
            WorkshopUrl = "https://steamcommunity.com/sharedfiles/filedetails/?id=" + item.PublishedFileId,
            NameMatches = Matches(item, query.SearchName)
        }).ToArray();
        var result = new
        {
            query.AppId,
            query.SearchName,
            RetrievedUtc = DateTime.UtcNow,
            NeedsUserConfirmation = true,
            TotalCount = items.Count,
            Matches = resultItems.Where(item => item.NameMatches).ToArray(),
            Items = resultItems
        };
        string outputPath = Path.ChangeExtension(Path.GetFullPath(configPath), ".list.json");
        JobContext.WriteJson(outputPath, result);
        Console.WriteLine(JsonSerializer.Serialize(result, JobContext.JsonOptions));
        Console.WriteLine("只读列表已写入：" + outputPath);
        Console.WriteLine("名称匹配只是候选；必须向用户展示游戏、名称、ID、链接并得到明确确认，才能上传。");
    }

    private static bool Matches(WorkshopPublishedItem item, string searchName)
    {
        string needle = Normalize(searchName);
        return needle.Length == 0 || new[] { item.Title, item.TitleChinese, item.TitleEnglish }
            .Any(title => Normalize(title).Contains(needle, StringComparison.OrdinalIgnoreCase));
    }

    private static string Normalize(string value) => string.Join(" ", (value ?? "").Normalize(NormalizationForm.FormKC)
        .Split((char[])null, StringSplitOptions.RemoveEmptyEntries));
}

internal sealed partial class SteamworksWorkshopUploader
{
    internal List<WorkshopPublishedItem> ListPublishedItems(uint appId, Action<string> log)
    {
        lock (steamApiLock)
        {
            EnsureSteamApiDll();
            WriteSteamAppId(DontStarveModToolsAppId);
            string previousDirectory = Directory.GetCurrentDirectory();
            bool initialized = false;
            try
            {
                Directory.SetCurrentDirectory(baseDirectory);
                if (!Native.SteamAPI_IsSteamRunning()) throw new InvalidOperationException("Steam 未运行，请先在线登录。");
                initialized = Native.SteamAPI_Init();
                if (!initialized) throw new InvalidOperationException("SteamAPI_Init 失败，请检查登录及工具权限。");
                IntPtr client = Native.SteamClient();
                int user = Native.SteamAPI_GetHSteamUser();
                int pipe = Native.SteamAPI_GetHSteamPipe();
                if (client == IntPtr.Zero || user == 0 || pipe == 0) throw new InvalidOperationException("无法取得 Steam 接口句柄。");
                IntPtr userInterface = GetSteamUser(client, user, pipe);
                IntPtr utils = GetSteamUtils(client, pipe);
                IntPtr ugc = GetSteamUgc(client, user, pipe);
                if (userInterface == IntPtr.Zero || utils == IntPtr.Zero || ugc == IntPtr.Zero)
                    throw new InvalidOperationException("无法取得 Steam 列表查询接口。");
                if (!Native.SteamAPI_ISteamUser_BLoggedOn(userInterface)) throw new InvalidOperationException("Steam 未在线登录。");
                ulong steamId = Native.SteamAPI_ISteamUser_GetSteamID(userInterface);
                uint accountId = (uint)(steamId & 0xffffffff);
                var byId = new Dictionary<ulong, WorkshopPublishedItem>();
                // Klei's legacy interface requires the tool's creator AppID;
                // using the consumer game's AppID returns an invalid query.
                const uint creatorId = DontStarveModToolsAppId;
                    foreach (WorkshopQueryLanguage language in CreateWorkshopQueryLanguages())
                    {
                        uint page = 1;
                        uint returned = 0;
                        while (true)
                        {
                            // Published / All types / LastUpdatedDesc.
                            ulong handle = Native.SteamAPI_ISteamUGC_CreateQueryUserUGCRequest(ugc, accountId, 0, -1, 3, creatorId, appId, page);
                            if (handle == 0 || handle == InvalidUpdateHandle) throw new InvalidOperationException("CreateQueryUserUGCRequest 失败。");
                            try
                            {
                                Native.SteamAPI_ISteamUGC_SetReturnMetadata(ugc, handle, true);
                                TrySetAllowCachedResponse(ugc, handle, 0, log);
                                SetQueryLanguage(ugc, handle, language, log);
                                ulong call = Native.SteamAPI_ISteamUGC_SendQueryUGCRequest(ugc, handle);
                                var response = WaitForCallResult<SteamUgcQueryCompleted>(utils, call, SteamUgcQueryCompletedCallback,
                                    "SendQueryUGCRequest(List)", 0, IntPtr.Zero, log);
                                if (response.Result != 1) throw new InvalidOperationException("查询已发布列表失败：" + ResultName(response.Result));
                                for (uint index = 0; index < response.NumResultsReturned; index++)
                                {
                                    if (!TryGetQueryResult(ugc, handle, index, out SteamUgcDetails details) || details.Result != 1)
                                        throw new InvalidOperationException("列表条目读取失败，不将不完整列表当作完整结果。");
                                    if (details.ConsumerAppId != appId || details.SteamIdOwner != steamId || details.PublishedFileId == 0) continue;
                                    MergePublishedItem(byId, details, GetQueryMetadata(ugc, handle, index),
                                        GetQueryPreviewUrl(ugc, handle, index), GetQueryTags(ugc, handle, index), language);
                                }
                                returned += response.NumResultsReturned;
                                log($"creator={creatorId} app={appId} language={language.Name} 第 {page} 页：{response.NumResultsReturned}/{response.TotalMatchingResults}");
                                if (returned >= response.TotalMatchingResults) break;
                                if (response.NumResultsReturned == 0 || page >= 1000)
                                    throw new InvalidOperationException("分页尚未读完，列表不完整，请稍后重查。");
                            }
                            finally { Native.SteamAPI_ISteamUGC_ReleaseQueryUGCRequest(ugc, handle); }
                            page++;
                        }
                    }
                return byId.Values.OrderByDescending(item => item.TimeUpdated).ThenBy(item => item.PublishedFileId).ToList();
            }
            finally
            {
                if (initialized) Native.SteamAPI_Shutdown();
                Directory.SetCurrentDirectory(previousDirectory);
            }
        }
    }
}
