// Literal-only modinfo reader extracted from KleiWorkshopUploader v2.8 (MulanPSL-2.0).
using System;
using System.Text.RegularExpressions;
namespace KleiWorkshopUploader
{
    internal static class ModInfo
    {
        internal static bool ReadLuaBoolField(string lua, string field)
        {
            foreach (Match match in Regex.Matches(lua ?? "", @"(?m)(?:^|\s)(?<field>" + Regex.Escape(field) + @")\s*=\s*(?<value>true|false)\b"))
                if (IsTopLevelLuaCodePosition(lua, match.Groups["field"].Index))
                    return match.Groups["value"].Value == "true";
            return false;
        }

        internal static string ReadLuaField(string lua, string field)
        {
            string pattern = @"(?ms)(?:^|\s)(?<field>" + Regex.Escape(field) + @")\s*=\s*(?:""(?<dq>(?:\\.|[^""])*)""|'(?<sq>(?:\\.|[^'])*)'|\[(?<eq>=*)\[(?<long>.*?)\]\k<eq>\])";
            MatchCollection matches = Regex.Matches(lua ?? "", pattern);
            foreach (Match m in matches)
            {
                if (!IsTopLevelLuaCodePosition(lua, m.Groups["field"].Index))
                {
                    continue;
                }

                if (m.Groups["dq"].Success)
                {
                    return DecodeLuaEscapes(m.Groups["dq"].Value);
                }
                if (m.Groups["sq"].Success)
                {
                    return DecodeLuaEscapes(m.Groups["sq"].Value);
                }
                return m.Groups["long"].Value;
            }
            return "";
        }

        private static bool IsTopLevelLuaCodePosition(string lua, int targetIndex)
        {
            if (String.IsNullOrEmpty(lua) || targetIndex < 0 || targetIndex > lua.Length)
            {
                return false;
            }

            int depth = 0;
            int i = 0;
            while (i < targetIndex)
            {
                char c = lua[i];
                if (c == '-' && i + 1 < targetIndex && lua[i + 1] == '-')
                {
                    int commentEnd = FindLuaCommentEnd(lua, i);
                    if (targetIndex < commentEnd)
                    {
                        return false;
                    }
                    i = commentEnd;
                    continue;
                }
                if (c == '"' || c == '\'')
                {
                    int stringEnd = FindLuaQuotedStringEnd(lua, i);
                    if (targetIndex < stringEnd)
                    {
                        return false;
                    }
                    i = stringEnd;
                    continue;
                }
                if (c == '[')
                {
                    int longStringEnd = FindLuaLongBracketEnd(lua, i);
                    if (longStringEnd > i)
                    {
                        if (targetIndex < longStringEnd)
                        {
                            return false;
                        }
                        i = longStringEnd;
                        continue;
                    }
                }
                if (c == '{')
                {
                    depth++;
                }
                else if (c == '}' && depth > 0)
                {
                    depth--;
                }
                i++;
            }

            return depth == 0;
        }

        private static int FindLuaCommentEnd(string lua, int start)
        {
            int longCommentEnd = FindLuaLongBracketEnd(lua, start + 2);
            if (longCommentEnd > start)
            {
                return longCommentEnd;
            }

            int newline = lua.IndexOf('\n', start + 2);
            return newline < 0 ? lua.Length : newline + 1;
        }

        private static int FindLuaQuotedStringEnd(string lua, int start)
        {
            char quote = lua[start];
            int i = start + 1;
            while (i < lua.Length)
            {
                if (lua[i] == '\\')
                {
                    i += 2;
                    continue;
                }
                if (lua[i] == quote)
                {
                    return i + 1;
                }
                i++;
            }
            return lua.Length;
        }

        private static int FindLuaLongBracketEnd(string lua, int start)
        {
            int eqCount = LuaLongBracketEquals(lua, start);
            if (eqCount < 0)
            {
                return -1;
            }

            string close = "]" + new string('=', eqCount) + "]";
            int closeIndex = lua.IndexOf(close, start + eqCount + 2, StringComparison.Ordinal);
            return closeIndex < 0 ? lua.Length : closeIndex + close.Length;
        }

        private static int LuaLongBracketEquals(string lua, int start)
        {
            if (String.IsNullOrEmpty(lua) || start < 0 || start >= lua.Length || lua[start] != '[')
            {
                return -1;
            }

            int i = start + 1;
            while (i < lua.Length && lua[i] == '=')
            {
                i++;
            }
            return i < lua.Length && lua[i] == '[' ? i - start - 1 : -1;
        }

        private static string DecodeLuaEscapes(string value)
        {
            return value
                .Replace("\\n", Environment.NewLine)
                .Replace("\\r", "\r")
                .Replace("\\t", "\t")
                .Replace("\\\"", "\"")
                .Replace("\\'", "'")
                .Replace("\\\\", "\\");
        }

    }
}
