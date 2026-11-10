-- 屏幕媒体库：上传（multipart 流式直写存储分区）+ 列表 + 删除
-- 传输机制照抄 luci-app-filetransfer：setfilehandler 必须在首次 formvalue 前注册，
-- 之后 multipart 各文件 part 依次回调，边收边写目标文件，不落 /tmp、不占内存。

local http = luci.http
local uci = require "luci.model.uci".cursor()

-- 类型只作标注展示（视频/GIF/图片/文件），不再限制上传与列表：解码能力交给
-- 设备端（图片 PIL、视频 ffmpeg→芯片 VPU rkmpp 优先/软解兜底），播不了的
-- 文件在轮播中自动跳过——凡是芯片/驱动能解的格式都能用。
-- （Lua pattern 无交替语法，扩展名用表查找而非单条正则）
local VIDEO_EXTS = {
	mp4=1, mkv=1, avi=1, mov=1, flv=1, ts=1, m2ts=1, mts=1, webm=1, m4v=1,
	["3gp"]=1, ["3g2"]=1, mpg=1, mpeg=1, vob=1, wmv=1, rm=1, rmvb=1, ogv=1,
	f4v=1, divx=1, asf=1, svi=1,
}
local IMG_EXTS = {
	png=1, jpg=1, jpeg=1, jfif=1, bmp=1, gif=1, webp=1, tif=1, tiff=1, ico=1,
	ppm=1, pgm=1, pbm=1, pnm=1, tga=1, pcx=1, dds=1,
}

local function media_dirs()
	local primary = uci:get("xgpscreen", "main", "media_dir") or "/mnt/mmc/screenmedia"
	local dirs = { primary }
	for _, d in ipairs({ "/mnt/mmc/screenmedia", "/overlay/screenmedia" }) do
		if d ~= dirs[1] then dirs[#dirs+1] = d end
	end
	return dirs
end

local function mountpoints()
	local mps = {}
	local f = io.open("/proc/mounts", "r")
	if f then
		for line in f:lines() do
			local mp = line:match("^%S+%s+(%S+)")
			if mp then mps[mp:gsub("\\040", " ")] = true end
		end
		f:close()
	end
	return mps
end

-- /mnt、/media 下的目录若所在分区没挂载，写入会静默落到 rootfs（flash overlay）——直接拒绝
local function storage_ready(dir, mps)
	if next(mps) == nil then return true, "?" end
	local p, parent = dir, nil
	while p and p ~= "" do
		if mps[p] then parent = p break end
		p = p:match("^(.*)/[^/]+/*$") or ""
	end
	parent = parent or "/"
	if (dir:match("^/mnt/") or dir:match("^/media/")) and parent == "/" then
		return false, parent
	end
	return true, parent
end

local function mkdirp(dir)
	if nixio.fs.stat(dir) then return true end
	local parts = {}
	for w in dir:gmatch("[^/]+") do parts[#parts+1] = w end
	local p = ""
	for _, w in ipairs(parts) do
		p = p .. "/" .. w
		if not nixio.fs.stat(p) then
			if not nixio.fs.mkdir(p) then return false end
		end
	end
	return nixio.fs.stat(dir) ~= nil
end

local function free_bytes(dir)
	local s = nixio.fs.statvfs(dir)
	if s and s.bavail and s.frsize then return s.bavail * s.frsize end
	return nil
end

local function size_str(n)
	if not n then return "-" end
	local units = { " B", " kB", " MB", " GB", " TB" }
	local i = 1
	while n >= 1024 and i < #units do n = n / 1024 i = i + 1 end
	return string.format(i == 1 and "%.0f%s" or "%.1f%s", n, units[i])
end

local function file_kind(name)
	local e = ((name or ""):match("%.([%w]+)$") or ""):lower()
	if e == "gif" then
		return "GIF"
	elseif VIDEO_EXTS[e] then
		return "视频"
	elseif IMG_EXTS[e] then
		return "图片"
	end
	return "文件"
end

local dirs = media_dirs()
local target = dirs[1]
local mps = mountpoints()
local ready = storage_ready(target, mps)
local freeb
local deny
if ready then
	if mkdirp(target) then
		freeb = free_bytes(target)
		local clen = tonumber(http.getenv("CONTENT_LENGTH") or "")
		if freeb and clen and clen > 0 and clen + 1048576 > freeb then
			deny = string.format("存储空间不足：剩余 %s，本次上传约需 %s",
				size_str(freeb), size_str(clen))
		end
	else
		deny = "无法创建存储目录：" .. target
		ready = false
	end
else
	deny = string.format("存储分区未挂载（%s 实际位于 rootfs），已取消上传以免写入 flash", target)
end

local upl = SimpleForm("upload", translate("上传媒体文件"), nil)
upl.reset = false
upl.submit = false
upl.description = string.format("存储目录：%s%s（支持多选；不限格式，凡是设备能解码的图片/GIF/视频都可上传）",
	target,
	freeb and "，剩余 " .. size_str(freeb) or "")

local sul = upl:section(SimpleSection, "", nil)
local fu = sul:option(FileUpload, "")
fu.template = "xgpmedia/upload"
local um = sul:option(DummyValue, "", nil)
um.template = "xgpmedia/dvalue"

local saved, failed = {}, {}
local fd, cur, fin, deny_told

http.setfilehandler(
	function(meta, chunk, eof)
		if cur == nil then
			-- 新文件 part 的首个回调（file_cb 只对带 filename 的 part 触发）
			cur = "skip"
			if deny then
				if not deny_told then
					failed[#failed+1] = deny
					deny_told = true
				end
			else
				local name = nixio.fs.basename(meta and meta.file or "")
				if name == "" or name == "." or name == ".." then
					failed[#failed+1] = "（无效文件名）"
			else
				-- 原子替换：写临时文件，eof 时 rename 覆盖——避免截断正在播放的同名文件。
				-- 最终名用干净的原名拼（不能从临时名剥 .part 推导——会把隐藏点一起留下）
				-- 格式不再白名单校验：解码能力交给设备端（PIL/ffmpeg），播放时自动跳过解不了的
				fd = nixio.open(target .. "/." .. name .. ".part", "w")
				if not fd then
					failed[#failed+1] = name .. "（无法创建文件）"
				else
					cur = target .. "/." .. name .. ".part"
					fin = target .. "/" .. name
				end
			end
			end
		end
		if fd and chunk and #chunk > 0 then
			fd:write(chunk)
		end
		if eof then
			if fd then
				fd:close()
				fd = nil
				local final = fin or (cur and cur:gsub("%.part$", ""))
				if final and os.rename(cur, final) then
					saved[#saved+1] = final:match("[^/]+$")
				else
					failed[#failed+1] = ((fin or cur) and (fin or cur):match("[^/]+$") or "?") .. "（重命名失败）"
					os.remove(cur)
				end
			end
			cur = nil
			fin = nil
		end
	end
)

if http.formvalue("upload") then
	if #saved > 0 then
		um.value = "已保存：" .. table.concat(saved, "、")
	end
	if #failed > 0 then
		um.value = (um.value and um.value .. "；" or "") .. "未上传：" .. table.concat(failed, "、")
	end
	if not um.value then
		um.value = "未选择文件或文件为空"
	end
end

local inits = {}
for _, d in ipairs(dirs) do
	local ok = storage_ready(d, mps)
	if ok then
		local names = nixio.fs.dir(d)
		if names then
			for f in names do
				local path = d .. "/" .. f
				local attr = nixio.fs.stat(path)
				-- 排除隐藏文件（.part 临时件/历史误产的 .xxx 命名都不进列表）；
				-- 不按扩展名过滤——任意格式都列出（类型列只作标注）
				if attr and attr.type == "reg" and not f:match("^%.") then
					inits[#inits+1] = {
						kind = file_kind(f),
						name = f,
						path = path,
						size = size_str(attr.size),
						mtime = os.date("%Y-%m-%d %H:%M", attr.mtime),
					}
				end
			end
		end
	end
end

local lst = SimpleForm("filelist", translate("媒体文件"), nil)
lst.reset = false
lst.submit = false
lst.description = "上传后在「屏幕设置」的页面里把路径填到图片/GIF/视频字段即可显示（填目录则自动轮播）。"

tb = lst:section(Table, inits)
tb:option(DummyValue, "kind", translate("类型"))
tb:option(DummyValue, "name", translate("文件名"))
tb:option(DummyValue, "path", translate("路径"))
tb:option(DummyValue, "size", translate("大小"))
tb:option(DummyValue, "mtime", translate("修改时间"))
btnrm = tb:option(Button, "remove", translate("删除"))
btnrm.render = function(self, section, scope)
	self.inputstyle = "remove"
	Button.render(self, section, scope)
end
btnrm.write = function(self, section)
	local e = inits[section]
	if e and nixio.fs.basename(e.path) == e.name then
		for _, d in ipairs(dirs) do
			if d == e.path:match("^(.*)/[^/]+$") then
				if nixio.fs.unlink(e.path) then
					table.remove(inits, section)
					return true
				end
			end
		end
	end
	return false
end

return upl, lst
