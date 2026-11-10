'use strict';
'require view';
'require ui';
'require form';
'require rpc';

var callNetworkInterfaceDump = rpc.declare({
	object: 'network.interface',
	method: 'dump',
	expect: { interface: [] }
});

var ITEM_CHOICES = {
	clock: '时钟（大字）',
	date: '日期',
	uptime: '运行时间',
	hostname: '主机名',
	ip_lan: '内网 IP (lan)',
	ip_wan: '外网 IP (wan)',
	cpu_temp: 'CPU 温度',
	temps: '温度总览（CPU/GPU/5G 模组/无线网卡）',
	load: '系统负载',
	mem: '内存占用',
	disk: '存储（overlay+媒体库+docker 汇总）',
	diskdetail: '存储分区明细（每分区容量+进度条）',
	modem: '5G 模组信息（名称/制造商/版本/AT端口）',
	lunar: '农历/节日',
	netgraph: '网速曲线（双折线+速率）',
	lanrate: 'LAN 口总流量（br-lan 累计上传/下载）',
	topsites: '网速前五网址（流量聚合+反解域名）',
	cpugraph: 'CPU 四核柱状图',
	signal: '5G 信号详情（RSRP/RSRQ/SINR）',
	devices: '在线设备列表',
	conncount: '连接数（阈值变色）',
	docker: 'Docker 容器状态',
	countdown: '倒计时（大字）',
	custom: '自定义文本',
	image: '图片（文件或目录轮播）',
	gif: 'GIF 动画',
	video: '视频（ffmpeg 播放，支持目录）',
	code: 'Python 代码页'
};

var PALETTE = [
	'#000000', '#FFFFFF', '#808080', '#C0C0C0',
	'#FF0000', '#FF7F00', '#FFAA00', '#FFFF00',
	'#00FF00', '#00FF88', '#00FFFF', '#00CED1',
	'#0000FF', '#4169E1', '#8A2BE2', '#FF00FF',
	'#FF1493', '#FFB6C1', '#7CFC00', '#ADFF2F'
];

var netIfaces = [];

return view.extend({
	load: function() {
		return callNetworkInterfaceDump()
			.then(function(res) {
				netIfaces = res || [];
			})
			.catch(function() {
				netIfaces = [];
			});
	},

	buildIfaceDatalist: function(formEl) {
		/* 本机 luci-base 的 form.js 不支持 o.datalist（静默忽略）：
		   手动注入原生 <datalist> 并绑定 list 属性，点击输入框即可弹出接口候选 */
		var inp = formEl.querySelector('input[id$="xgpscreen.main.net_iface"]');
		if (!inp || inp.getAttribute('list'))
			return;
		var seen = {}, devs = [];
		(netIfaces || []).forEach(function(ifc) {
			var dev = ifc.l3_device || ifc.device;
			if (!dev || seen[dev])
				return;
			seen[dev] = true;
			devs.push(dev);
		});
		if (!devs.length)
			return;
		var old = document.getElementById('xgp-net-iface-dl');
		if (old)
			old.parentNode.removeChild(old);
		var dl = document.createElement('datalist');
		dl.id = 'xgp-net-iface-dl';
		devs.forEach(function(d) {
			var opt = document.createElement('option');
			opt.value = d;
			dl.appendChild(opt);
		});
		document.body.appendChild(dl);
		inp.setAttribute('list', 'xgp-net-iface-dl');
	},

	buildColorHelper: function(formEl) {
		/* 每个颜色字段旁挂原生取色器：点选即时写入输入框（双向同步） */
		['bg_color', 'fg_color', 'title_color'].forEach(function(name) {
			var inp = formEl.querySelector('input[id$="xgpscreen.main.' + name + '"]');
			if (!inp)
				return;
			var norm = function(v) {
				return (/^#[0-9a-fA-F]{6}$/.test(v || '')) ? v : '#000000';
			};
			var cp = E('input', {
				'type': 'color',
				'style': 'width:52px;height:38px;margin-left:10px;vertical-align:middle;' +
					'border:2px solid #52525b;border-radius:6px;background:#2b2b33;cursor:pointer;padding:2px'
			});
			var commit = function() {
				/* 取色器值为准，整体赋值（防拼接脏值） */
				inp.value = cp.value;
				inp.dispatchEvent(new Event('input', { bubbles: true }));
				inp.dispatchEvent(new Event('change', { bubbles: true }));
			};
			var lazySync = function() {
				if (/^#[0-9a-fA-F]{6}$/.test(inp.value || ''))
					cp.value = inp.value;
			};
			/* 表单值异步填充：轮询到有效值即同步默认色；点开时再兜底同步 */
			var tries = 0;
			var poll = function() {
				lazySync();
				if (cp.value === '#000000' && inp.value && ++tries < 25)
					setTimeout(poll, 300);
			};
			poll();
			cp.addEventListener('click', lazySync);
			cp.addEventListener('focus', lazySync);
			/* input=拖动实时写入；change=部分浏览器仅确认时触发 */
			cp.addEventListener('input', commit);
			cp.addEventListener('change', commit);
			/* 手改输入框也回同步取色器 */
			inp.addEventListener('input', lazySync);
			inp.addEventListener('change', lazySync);
			inp.parentNode.appendChild(cp);
		});
		/* 倒计时日期：输入框本身转 date 类型——点击整个输入框即弹日历，无附加元素 */
		var attachDate = function(inp) {
			if (!inp || inp.__dp)
				return;
			inp.__dp = true;
			inp.type = 'date';
			inp.style.height = '34px';
			/* 原生 date 输入在多数 Chromium 里点文字区只聚焦不弹窗（仅右侧图标开），
			   showPicker() 强制点击整个输入框即弹出日历；老浏览器静默回退原生行为 */
			inp.addEventListener('click', function() {
				try { inp.showPicker(); } catch (e) { }
			});
		};
		var dateFields = function() {
			document.querySelectorAll('input[id$=".countdown_date"]').forEach(attachDate);
		};
		dateFields();
		/* LuCI 编辑模态框挂在 body 下而非 form 内，须观察整个文档 */
		new MutationObserver(dateFields).observe(document.body, { childList: true, subtree: true });
	},

	CODE_EXAMPLE: [
		'# XGP 屏幕代码页完整示例：时钟 + 农历 + 内存条 + 运行时间',
		'# 可用: d=画笔 img=图像 w,h=画布(320x172) f1大/f2标题/f3小/f4值(字体)',
		"#       collect('mem'等)=内置条目 lunar_str()=农历 time/os=标准库",
		'G = (0, 255, 136)   # 主色',
		'O = (255, 170, 0)   # 强调色',
		'B = (45, 45, 55)    # 底色',
		'',
		"# 标题与分隔线",
		"d.text((10, 4), '我的状态页', font=f3, fill=O)",
		'd.line((10, 26, w - 10, 26), fill=B)',
		'',
		"# 大时钟（水平居中 anchor='ma'）",
		"d.text((w // 2, 40), time.strftime('%H:%M'), font=f1, fill=G, anchor='ma')",
		'',
		'# 日期 + 农历',
		"d.text((w // 2, 96), time.strftime('%m-%d ') + lunar_str(), font=f3, fill=G, anchor='ma')",
		'',
		"# 内存进度条：collect 返回如 '512M / 987M (51%)'",
		'import re',
		"m = re.search(r'\\((\\d+)%\\)', collect('mem'))",
		'pct = int(m.group(1)) if m else 0',
		"d.text((10, 122), '内存', font=f4, fill=G)",
		'd.rectangle((60, 126, w - 10, 138), fill=B)',
		'd.rectangle((60, 126, 60 + (w - 70) * pct // 100, 138), fill=O)',
		"d.text((w - 10, 118), '%d%%' % pct, font=f4, fill=G, anchor='ra')",
		'',
		'# 底部：运行时间',
		"d.text((10, 150), '已运行 ' + collect('uptime'), font=f3, fill=G)"
	].join('\\n'),

	buildCodeHelper: function() {
		/* 代码页：一键插入完整示例 + 移动端输入优化（关自动大写/联想、等宽小号字） */
		var attach = function(ta) {
			if (!ta || ta.__xgp)
				return;
			ta.__xgp = true;
			ta.setAttribute('autocapitalize', 'off');
			ta.setAttribute('autocomplete', 'off');
			ta.setAttribute('autocorrect', 'off');
			ta.setAttribute('spellcheck', 'false');
			ta.style.fontFamily = 'monospace';
			ta.style.fontSize = '13px';
			var btn = E('button', {
				'type': 'button',
				'class': 'cbi-button cbi-button-neutral',
				'style': 'margin-top:6px;padding:10px 16px;font-size:14px;min-height:38px'
			}, _('插入示例代码'));
			btn.addEventListener('click', function() {
				if (ta.value.trim() && !confirm(_('当前代码将被示例覆盖，继续？')))
					return;
				ta.value = this.CODE_EXAMPLE;
				ta.dispatchEvent(new Event('input', { bubbles: true }));
				ta.dispatchEvent(new Event('change', { bubbles: true }));
			}.bind(this));
			ta.parentNode.appendChild(btn);
		}.bind(this);
		var codeFields = function() {
			document.querySelectorAll('textarea[id$=".code_text"]').forEach(attach);
		};
		codeFields();
		/* GridSection 编辑模态框挂在 body 下，须观察整个文档（与日期字段同套路） */
		new MutationObserver(codeFields).observe(document.body, { childList: true, subtree: true });
	},

	render: function() {
		var m, s, o;

		m = new form.Map('xgpscreen', _('XGP V3 屏幕设置'),
			_('自定义 320x240 屏幕显示。与 LVGL 界面互斥；保存后下一轮刷新即生效。图形组件（曲线/柱状等）每页约放 1-2 个。'));

		s = m.section(form.TypedSection, 'main', _('基本设置'));
		s.anonymous = true;

		o = s.option(form.Flag, 'enabled', _('启用自定义渲染器'));
		o.rmempty = false;
		o.default = '1';

		o = s.option(form.ListValue, 'rotate', _('旋转角度'), _('默认 0°（与 LVGL 相同的直写方向）。仅当画面方向不对时才改'));
		o.value('0', '0°（默认）');
		o.value('90', '90°');
		o.value('180', '180°');
		o.value('270', '270°');
		o.default = '0';

		o = s.option(form.Flag, 'invert', _('反色显示'));
		o.rmempty = false;

		o = s.option(form.Value, 'interval', _('页面切换间隔（秒）'));
		o.datatype = 'range(1, 3600)';
		o.default = '5';

		o = s.option(form.Value, 'video_speed', _('视频播放倍速'),
			_('1=原速；1.5~2 可缓解卡顿（加速播放，每帧都是新内容，流畅快放）'));
		o.datatype = 'range(0.5,4)';
		o.default = '1';
		o.rmempty = true;

		o = s.option(form.Value, 'video_fps', _('视频写屏节拍（fps）'),
			_('视频帧写屏的匀速节拍，需不超过屏幕 SPI 刷新上限（约 20fps）。' +
				'内部有 4 帧缓冲吸收解码抖动：供给 25fps、按此节拍消费，队列满自动丢旧帧保延迟；' +
				'设得过高会退回随机漏刷的卡顿状态'));
		o.datatype = 'range(10,25)';
		o.default = '20';
		o.rmempty = true;

		o = s.option(form.Value, 'media_dir', _('媒体库目录'),
			_('浏览器上传的图片/视频存放目录，也是媒体库页面管理的目录'));
		o.rmempty = true;

		o = s.option(form.Value, 'net_iface', _('网速监控网卡'),
			_('留空自动选择 wwan0_1/eth0 等；点击输入框可从当前实际接口中选择，也可手动输入任意接口名'));
		o.rmempty = true;
		/* 候选接口由 buildIfaceDatalist 注入原生 datalist（本机 form.js 不支持 o.datalist） */

		o = s.option(form.Value, 'show_title', _('顶部标题文字'),
			_('仅信息类页面(状态/组件/自定义)顶部显示；图片/GIF/视频等整屏页不显示'));
		o.default = 'XGP-V3';

		o = s.option(form.Value, 'bg_color', _('背景色'), '如 #000000');
		o.datatype = 'hexcolor';

		o = s.option(form.Value, 'fg_color', _('内容颜色'), '如 #00FF88');
		o.datatype = 'hexcolor';

		o = s.option(form.Value, 'title_color', _('标题颜色'), '如 #FFAA00');
		o.datatype = 'hexcolor';

		s = m.section(form.GridSection, 'page', _('显示页面'),
			_('多页轮播。图片/GIF/视频/代码页以每页第一个类型为准；其余为普通条目页。'));
		s.addremove = true;
		s.anonymous = false;
		s.nodescriptions = true;

		o = s.option(form.Flag, 'enabled', _('启用'));
		o.rmempty = false;
		o.default = '1';
		o.editable = true;

		o = s.option(form.Value, 'title', _('页面名称'));
		o.default = _('页面');

		o = s.option(form.DynamicList, 'items', _('显示条目/类型'));
		for (var k in ITEM_CHOICES)
			o.value(k, ITEM_CHOICES[k]);
		o.rmempty = false;

		o = s.option(form.Value, 'countdown_label', _('倒计时名称'), _('如：生日 / 项目截止'));

		o = s.option(form.Value, 'countdown_date', _('倒计时日期'), _('YYYY-MM-DD'));

		o = s.option(form.TextValue, 'custom_text', _('自定义文本'));
		o.rows = 5;

		o = s.option(form.Value, 'image_path', _('图片路径'), _('文件或目录（目录轮播）。不限格式：设备能解码的图片都能播，目录里解不了的文件自动跳过'));

		o = s.option(form.Value, 'gif_path', _('GIF 路径'));

		o = s.option(form.Value, 'video_path', _('视频路径'), _('文件或目录（目录逐个播放）。不限格式：ffmpeg/芯片 VPU 能解的都能播'));

		o = s.option(form.ListValue, 'fit_mode', _('显示比例'),
			_('仅图片/GIF/视频整页生效：控制媒体与屏幕 320x172 宽高比不一致时的适配方式。') +
			_('「完整显示」模式下图片/GIF 留边区域衬页面背景色，视频统一黑边。'));
		o.value('cover', _('裁切填满（默认）'));
		o.value('stretch', _('拉伸铺满（宽高比变形）'));
		o.value('contain', _('完整显示（等比缩小留边）'));
		o.default = 'cover';

		o = s.option(form.ListValue, 'rotate', _('显示旋转'),
			_('仅图片/GIF/视频整页生效：画面逆时针旋转后铺满屏幕（如竖版照片转横显示）。') +
			_('与「基本设置」的全局旋转叠加（相加后取模 360°）。'));
		o.value('0', '0°（默认）');
		o.value('90', '90°（逆时针）');
		o.value('180', '180°');
		o.value('270', '270°（顺时针 90°）');
		o.default = '0';

		o = s.option(form.TextValue, 'code_text', _('Python 代码'),
			_('整页自由绘制，页面轮播到该页时执行一次（预览缩略图即实际效果）。') +
			_('可用变量：d=画笔、img=图像、w/h=画布宽高(320x172)、f1=大字/f2=标题/f3=小字/f4=数值（四种字体）、') +
			_("collect('mem'/'cpu_temp'/'uptime'/'hostname'等)=取内置条目数据、lunar_str()=农历、time/os=标准库。") +
			_('绘图：d.text((x,y),\'文字\',font=f4,fill=(R,G,B))、d.rectangle/d.line/d.ellipse。') +
			_('死循环与 exit() 会被自动中止，不会弄坏屏幕服务；点「插入示例代码」看完整用法。'));
		o.rows = 10;
		o.placeholder = 'd.text((10, 50), "CPU: " + collect("cpu_temp"), font=f4, fill=(0,255,255))';

		return m.render().then(function(formEl) {
			this.buildColorHelper(formEl);
			this.buildIfaceDatalist(formEl);
			this.buildCodeHelper();
			return formEl;
		}.bind(this));
	}
});
