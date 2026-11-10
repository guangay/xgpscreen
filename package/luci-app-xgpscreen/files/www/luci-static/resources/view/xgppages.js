'use strict';
'require view';
'require uci';
'require ui';
'require request';

/* 页面预览与排序：离屏渲染缩略图（/admin/services/xgpscreen/preview?page=xxx）+
   拖拽调整轮播顺序。渲染器按 section 名排序轮播 → 重排由服务端一次性完成
   （POST /admin/services/xgpscreen/reorder，内容按目标顺序置换进按名排序的槽位）。 */

var KIND_NAMES = {
	image: '图片', gif: 'GIF', video: '视频', code: '代码'
};

/* fit_mode → CSS object-fit（媒体卡片内联播放与设备显示同一适配语义） */
var FIT_CSS = { cover: 'cover', stretch: 'fill', contain: 'contain' };
var FIT_NAMES = { cover: '裁切填满', stretch: '拉伸', contain: '完整显示' };

return view.extend({
	load: function() {
		return uci.load('xgpscreen');
	},

	previewUrl: function(sid) {
		return L.url('admin/services/xgpscreen/preview') +
			'?page=' + encodeURIComponent(sid) + '&t=' + Date.now();
	},

	mediaUrl: function(sid) {
		return L.url('admin/services/xgpscreen/mediafile') +
			'?page=' + encodeURIComponent(sid) + '&t=' + Date.now();
	},

	/* 服务端原子排序：order = 目标顺序的 sid 数组 */
	applyOrder: function(order) {
		return request.post(L.url('admin/services/xgpscreen/reorder'), {
			token: L.env.token,
			order: JSON.stringify(order)
		}).then(function(r) {
			return r.json();
		}).then(function(j) {
			if (!j || !j.ok)
				throw new Error((j && j.error) || _('未知错误'));
		});
	},

	toggleEnabled: function(sid, on) {
		uci.set('xgpscreen', sid, 'enabled', on ? '1' : '0');
		return uci.save().then(function() { location.reload(); });
	},

	/* 媒体页（image/gif/video）：流式取真实文件内联播放——GIF 原生动图、
	   video 静音自动循环，object-fit 按该页 fit_mode 映射（与设备同一适配语义）。
	   打不开（未配置/浏览器解不了的容器）自动回退离屏渲染 PNG 预览；
	   其余页（信息/代码）直接用离屏 PNG（代码页预览即真实执行效果）。
	   页面显示旋转用 CSS transform 呈现（CSS 正角=顺时针，PIL=逆时针，
	   故取 -rot 对齐设备方向）；90/270 时内层容器换轴居中，不裁内容。 */
	buildPreview: function(p, sid, self) {
		var kind = (p.items && p.items[0]) || '';
		var fit = FIT_CSS[p.fit_mode] || 'cover';
		var rot = [0, 90, 180, 270].indexOf(parseInt(p.rotate, 10)) >= 0
			? parseInt(p.rotate, 10) : 0;
		var box = E('div', {
			'style': 'width:200px;height:107px;border-radius:6px;overflow:hidden;' +
				'display:block;position:relative;background:' + (kind == 'video' ? '#000'
					: (uci.get('xgpscreen', 'main', 'bg_color') || '#000'))
		});
		var mediaStyle = 'width:100%;height:100%;object-fit:' + fit + ';display:block';
		var toPng = function() {
			box.innerHTML = '';
			box.style.height = 'auto';
			box.appendChild(E('img', {
				'src': self.previewUrl(sid),
				'style': 'width:200px;height:auto;object-fit:contain;background:#000;' +
					'border-radius:6px;pointer-events:none;display:block',
				'loading': 'lazy',
				'onerror': 'this.src=\'data:image/svg+xml;utf8,' +
					encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="107">' +
						'<rect width="100%" height="100%" fill="#111"/>' +
						'<text x="100" y="54" fill="#555" font-size="12" text-anchor="middle">预览失败</text></svg>') + '\''
			}));
		};
		var appendMedia = function(el) {
			if (rot == 90 || rot == 270) {
				var inner = E('div', {
					'style': 'position:absolute;width:107px;height:200px;' +
						'left:46.5px;top:-46.5px;transform:rotate(' + (-rot) + 'deg);' +
						'transform-origin:50% 50%;overflow:hidden'
				});
				inner.appendChild(el);
				box.appendChild(inner);
			} else {
				if (rot == 180)
					el.style.transform = 'rotate(180deg)';
				box.appendChild(el);
			}
		};
		if (kind == 'image' || kind == 'gif') {
			var im = E('img', {
				'src': self.mediaUrl(sid),
				'style': mediaStyle,
				'loading': 'lazy'
			});
			im.addEventListener('error', toPng);
			appendMedia(im);
		} else if (kind == 'video') {
			var v = E('video', {
				'src': self.mediaUrl(sid),
				'preload': 'metadata',
				'style': mediaStyle
			});
			/* 布尔属性须 property 赋值才可靠：muted 的内容属性不反射到
			   IDL 属性（只改 defaultMuted），autoplay 策略判定看的是
			   el.muted——属性设了也等于没设。muted 先行再 play() 兜底 */
			v.muted = true;
			v.autoplay = true;
			v.loop = true;
			v.setAttribute('playsinline', '');
			v.addEventListener('error', toPng);
			appendMedia(v);
			v.play().catch(function() {});
		} else {
			box.style.height = 'auto';
			box.appendChild(E('img', {
				'src': self.previewUrl(sid),
				'style': 'width:200px;height:auto;object-fit:contain;background:#000;' +
					'border-radius:6px;pointer-events:none;display:block',
				'loading': 'lazy',
				'onerror': 'this.src=\'data:image/svg+xml;utf8,' +
					encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="107">' +
						'<rect width="100%" height="100%" fill="#111"/>' +
						'<text x="100" y="54" fill="#555" font-size="12" text-anchor="middle">预览失败</text></svg>') + '\''
			}));
		}
		return box;
	},

	buildCard: function(p, idx, self, grid, gridOrder) {
		var sid = p['.name'];
		var kind = (p.items && p.items[0]) || '';
		var en = p.enabled != '0';
		var kindName = KIND_NAMES[kind] || '组件页';
		if (kind in KIND_NAMES && kind != 'code') {
			var rot = parseInt(p.rotate, 10);
			kindName += '（' + (FIT_NAMES[p.fit_mode] || FIT_NAMES.cover) +
				(([0, 90, 180, 270].indexOf(rot) >= 0 && rot) ? '·' + rot + '°' : '') + '）';
		}
		var baseOpacity = en ? 1 : 0.55;
		var card = E('div', {
			'data-sid': sid,
			'data-title': p.title || sid,
			'draggable': en,
			'style': 'width:212px;border:2px solid #52525b;border-radius:10px;' +
				'padding:6px;text-align:center;cursor:grab;user-select:none;' +
				'background:#2b2b33;transition:border-color .15s;opacity:' + baseOpacity
		}, [
			this.buildPreview(p, sid, self),
			E('div', { 'class': 'xgp-card-title',
				'style': 'font-size:13px;margin-top:5px;font-weight:600' },
				(idx + 1) + '. ' + (p.title || sid)),
			E('div', { 'style': 'font-size:12px;color:#9a9aa5;margin:3px 0' }, kindName),
			E('button', {
				'class': 'btn cbi-button',
				/* 状态按钮配色自包含（卡片本身是固定深色底，不依赖主题类）：
				   启用=实心绿、禁用=暗底灰字+描边，一眼可辨 */
				'style': 'padding:3px 14px;font-size:12px;font-weight:600;min-height:0;' +
					(en ? 'background:#2f8f5f;border:1px solid #2f8f5f;color:#ffffff'
					    : 'background:#3a3a42;border:1px solid #6b6b76;color:#9a9aa5'),
				'click': ui.createHandlerFn(self, function() {
					return self.toggleEnabled(sid, !en);
				})
			}, en ? _('已启用 · 禁用') : _('已禁用 · 启用'))
		]);

		card.addEventListener('dragstart', function(ev) {
			ev.dataTransfer.setData('text/plain', sid);
			ev.dataTransfer.effectAllowed = 'move';
			this.style.opacity = 0.3;
		});
		card.addEventListener('dragend', function() {
			this.style.opacity = baseOpacity;
			Array.prototype.forEach.call(grid.querySelectorAll('[data-sid]'), function(c) {
				c.style.borderColor = '#52525b';
			});
		});
		card.addEventListener('dragover', function(ev) {
			ev.preventDefault();
			ev.dataTransfer.dropEffect = 'move';
			this.style.borderColor = '#2f8f5f';
		});
		card.addEventListener('dragleave', function() {
			this.style.borderColor = '#52525b';
		});
		card.addEventListener('drop', function(ev) {
			ev.preventDefault();
			var from = ev.dataTransfer.getData('text/plain');
			var to = this.getAttribute('data-sid');
			if (!from || from == to)
				return;
			var order = gridOrder();
			var fi = order.indexOf(from), ti = order.indexOf(to);
			if (fi < 0 || ti < 0)
				return;
			order.splice(fi, 1);
			order.splice(ti, 0, from);
			self.applyOrder(order).then(function() {
				/* 原地反馈：按新顺序搬移现有卡片节点（缩略图不重载）+ 重排序号，
				   不整页刷新；拖拽感即时可见 */
				order.forEach(function(sid) {
					var c = grid.querySelector('[data-sid="' + sid + '"]');
					if (c)
						grid.appendChild(c);
				});
				Array.prototype.forEach.call(
					grid.querySelectorAll('[data-sid]'),
					function(c, i) {
						var t = c.querySelector('.xgp-card-title');
						if (t)
							t.textContent = (i + 1) + '. ' + (c.getAttribute('data-title') || '');
						c.style.borderColor = '#2f8f5f';
						window.setTimeout(function() { c.style.borderColor = '#52525b'; }, 900);
					});
			}).catch(function(e) {
				ui.addNotification(null,
					E('p', _('排序保存失败：') + e), 'error');
			});
		});
		return card;
	},

	render: function() {
		var self = this;
		var pages = uci.sections('xgpscreen', 'page')
			.sort(function(a, b) { return a['.name'] < b['.name'] ? -1 : 1; });

		var grid = E('div', { 'style': 'display:flex;flex-wrap:wrap;gap:12px' });
		var gridOrder = function() {
			return Array.prototype.map.call(
				grid.querySelectorAll('[data-sid]'),
				function(c) { return c.getAttribute('data-sid'); });
		};

		for (var i = 0; i < pages.length; i++)
			grid.appendChild(this.buildCard(pages[i], i, self, grid, gridOrder));

		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, _('页面预览与排序')),
			E('div', { 'class': 'cbi-section-descr' }, [
				_('缩略图直接播放真实媒体：GIF 原生动图、视频静音循环播放，显示比例与设备一致；浏览器解不了的格式自动回退设备离屏渲染图（视频为首帧）。Python 代码页预览即代码真实执行效果。'),
				E('br'),
				_('拖拽卡片调整轮播顺序，松手即保存生效；单个页面的内容编辑请到「页面设置」。')
			]),
			pages.length ? grid : E('div', { 'class': 'cbi-section-descr' },
				_('暂无页面，请先到「页面设置」添加。'))
		]);
	}
});
