-- 屏幕媒体库页（上传/列表/删除）+ 页面预览/排序端点
-- 上传机制与 luci-app-filetransfer 相同：CBI 表单 multipart POST（sysauth+token 由
-- dispatcher 处理），服务端 http.setfilehandler 流式直写媒体目录，不经 /tmp。

module("luci.controller.xgpmedia", package.seeall)

function index()
	if not nixio.fs.access("/etc/config/xgpscreen") then
		return
	end
	entry({"admin", "services", "xgpscreen", "media"}, form("xgpmedia"), _("媒体库"), 20)
	entry({"admin", "services", "xgpscreen", "preview"}, call("action_preview")).leaf = true
	entry({"admin", "services", "xgpscreen", "mediafile"}, call("action_mediafile")).leaf = true
	entry({"admin", "services", "xgpscreen", "reorder"}, call("action_reorder")).leaf = true
end

function action_preview()
	local http = require "luci.http"
	local section = http.formvalue("page") or ""
	if not section:match("^[%w_]+$") then
		http.status(400, "Bad Request")
		return
	end
	local p = io.popen("/usr/bin/xgpscreen.py --preview " .. section .. " 2>/dev/null", "r")
	if not p then
		http.status(500, "Internal Server Error")
		return
	end
	local hdr = p:read(4)
	if hdr ~= string.char(0x89) .. "PNG" then
		p:close()
		http.status(500, "Internal Server Error")
		http.prepare_content("text/plain")
		http.write("preview failed")
		return
	end
	http.prepare_content("image/png")
	http.write(hdr)
	while true do
		local chunk = p:read(65536)
		if not chunk or #chunk == 0 then break end
		http.write(chunk)
	end
	p:close()
end

-- 媒体文件流式输出（页面预览卡片内联播放）：?page=sid 解析该页配置的首个媒体
-- 文件（目录取排序后首个非隐藏常规文件，与渲染器 _media_files 同语义）。
-- 扩展名→MIME 映射只决定浏览器能否内联显示；不在表内/浏览器解不了的格式由
-- 前端回退到 PNG 离屏预览（设备端播放从来不受此表限制）。支持单段 Range
-- （<video> 进度拖动必需）。鉴权与 preview 一致（admin sysauth 由 dispatcher 管）。
local MEDIA_MIME = {
	mp4 = "video/mp4", m4v = "video/mp4", webm = "video/webm",
	mkv = "video/x-matroska", mov = "video/quicktime", avi = "video/x-msvideo",
	flv = "video/x-flv", ts = "video/mp2t", m2ts = "video/mp2ts", mts = "video/mp2ts",
	mpg = "video/mpeg", mpeg = "video/mpeg", vob = "video/mpeg",
	wmv = "video/x-ms-wmv", ["3gp"] = "video/3gpp", ["3g2"] = "video/3gpp2",
	ogv = "video/ogg", f4v = "video/x-f4v", divx = "video/x-divx",
	asf = "video/x-ms-asf",
	gif = "image/gif", png = "image/png", jpg = "image/jpeg", jpeg = "image/jpeg",
	jfif = "image/jpeg", bmp = "image/bmp", webp = "image/webp", ico = "image/x-icon",
	tif = "image/tiff", tiff = "image/tiff",
}

local function page_media_path(sid)
	local uci = require "luci.model.uci".cursor()
	local s = uci:get_all("xgpscreen", sid)
	if type(s) ~= "table" then return nil end
	local items = s.items
	if type(items) == "string" then items = { items } end
	if type(items) ~= "table" then return nil end
	local field = ({ image = "image_path", gif = "gif_path", video = "video_path" })[items[1]]
	if not field then return nil end
	local path = s[field]
	if type(path) ~= "string" or path == "" then return nil end
	local st = nixio.fs.stat(path)
	if not st then return nil end
	if st.type == "reg" then return path end
	if st.type == "dir" then
		-- 与渲染器一致：排序后首个非隐藏常规文件
		local best
		for f in nixio.fs.dir(path) do
			if not f:match("^%.") and nixio.fs.stat(path .. "/" .. f, "type") == "reg" then
				if not best or f < best then best = f end
			end
		end
		if best then return path .. "/" .. best end
	end
	return nil
end

function action_mediafile()
	local http = require "luci.http"
	local section = http.formvalue("page") or ""
	if not section:match("^[%w_]+$") then
		http.status(400, "Bad Request")
		return
	end
	local path = page_media_path(section)
	if not path then
		http.status(404, "Not Found")
		return
	end
	local ext = path:match("%.([%w]+)$")
	local mime = ext and MEDIA_MIME[ext:lower()]
	local st = mime and nixio.fs.stat(path)
	local f = st and io.open(path, "rb")
	if not f then
		http.status(415, "Unsupported Media Type")
		http.prepare_content("text/plain")
		http.write("not inlinable")
		return
	end
	local size = st.size
	-- Range: bytes=a-b / bytes=a-（后缀型 -n 少见，回退 200 全量）。
	-- 实测 uhttpd 的 CGI 头白名单不透传 Range（env 只有 UA/Accept/Host 等），
	-- 浏览器 <video> 拿 200 全量渐进播放不受影响、仅进度拖动不可用——
	-- 解析逻辑保留，将来换转发层（反代透传头）即自动生效。
	-- 数值一律走 %.0f 拼接：Lua5.1(int32 构建) 的 %d 对 >2GB 文件直接抛错
	local first, last = 0, size - 1
	local partial = false
	local rng = http.getenv("HTTP_RANGE") or ""
	local a, b = rng:match("^bytes=(%d+)-(%d*)$")
	if a then
		first = tonumber(a)
		if b and #b > 0 then last = math.min(tonumber(b), size - 1) end
		if first > last or first >= size then
			f:close()
			http.status(416, "Range Not Satisfiable")
			http.header("Content-Range", ("bytes */%.0f"):format(size))
			http.prepare_content("text/plain")
			http.write("range error")
			return
		end
		partial = true
	end
	http.header("Cache-Control", "no-store")
	http.header("Content-Length", ("%.0f"):format(last - first + 1))
	if partial then
		http.status(206, "Partial Content")
		http.header("Content-Range",
			("bytes %.0f-%.0f/%.0f"):format(first, last, size))
	else
		http.status(200, "OK")
	end
	http.prepare_content(mime)
	f:seek("set", first)
	while true do
		local chunk = f:read(65536)
		if not chunk or #chunk == 0 then break end
		http.write(chunk)
	end
	f:close()
end

-- 页面排序：POST {token, order=[sid,...目标顺序]}。
-- 渲染器按 section 名排序轮播 → 重排 = 把内容按目标顺序置换进按名排序的槽位。
-- 服务端 cursor 一次性完成（清空选项→按序写回→commit），避免客户端 uci 差量
-- 在 save 中途失败造成半套配置的风险。
function action_reorder()
	local http = require "luci.http"
	local dsp = require "luci.dispatcher"

	http.prepare_content("application/json")

	local jsonc = require "luci.jsonc"
	local token, order
	local ct = http.getenv("CONTENT_TYPE") or ""
	if ct:match("application/json") then
		-- LuCI request.post 发 JSON body（order 字段可能是 JSON 字符串或原生数组）
		local j = jsonc.parse(http.content() or "") or {}
		token = j.token
		order = (type(j.order) == "string") and jsonc.parse(j.order) or j.order
	else
		token = http.formvalue("token")
		order = jsonc.parse(http.formvalue("order") or "")
	end
	if http.getenv("REQUEST_METHOD") ~= "POST" or token ~= dsp.context.authtoken then
		http.status(403, "Forbidden")
		http.write('{"ok":false,"error":"forbidden"}')
		return
	end
	if type(order) ~= "table" then
		http.status(400, "Bad Request")
		http.write('{"ok":false,"error":"bad order"}')
		return
	end

	local uci = require "luci.model.uci".cursor()
	local secs, names = {}, {}
	uci:foreach("xgpscreen", "page", function(s)
		local o = {}
		for k, v in pairs(s) do
			if k:sub(1, 1) ~= "." then o[k] = v end
		end
		secs[s[".name"]] = o
		names[#names+1] = s[".name"]
	end)

	if #order ~= #names then
		http.status(400, "Bad Request")
		http.write('{"ok":false,"error":"length mismatch"}')
		return
	end
	local seen = {}
	for _, n in ipairs(order) do
		if secs[n] == nil or seen[n] then
			http.status(400, "Bad Request")
			http.write('{"ok":false,"error":"unknown page"}')
			return
		end
		seen[n] = true
	end

	for _, n in ipairs(names) do
		for k in pairs(secs[n]) do
			uci:delete("xgpscreen", n, k)
		end
	end
	table.sort(names)
	for i, src in ipairs(order) do
		local dst = names[i]
		for k, v in pairs(secs[src]) do
			uci:set("xgpscreen", dst, k, v)
		end
	end
	uci:commit("xgpscreen")
	http.write('{"ok":true}')
end
