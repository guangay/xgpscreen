'use strict';
'require baseclass';
'require fs';
/* XGP 硬件温度卡片（全量明细版）：处理器/图形处理器/无线网卡/5G 模组。
 * 数据来自 /usr/bin/xgp-temps 采集器（与小屏幕共享同一份兼容逻辑）。
 * 显示策略：组件主行给汇总值（多传感器=最高），其下逐传感器明细子行
 * （缩进+淡色）——"每个采集器都要显示"；modem_age>15s 表示忙期回吐的
 * 陈旧值，标注秒数。阈值变色：>60 橙 / >75 红。 */

var DIM_STYLE = 'opacity:.55;padding-left:1.6em';

function tempNode(t, dim) {
	var color = (t > 75) ? '#e00000' : (t > 60) ? '#e8a000' : null;
	var el = E('span', {}, [ '%d °C'.format(t) ]);
	if (color)
		el.style.color = color;
	if (dim)
		el.style.opacity = '.8';
	return el;
}

function dimNode(txt) {
	return E('span', { 'style': 'opacity:.55' }, [ txt ]);
}

return baseclass.extend({
	title: _('硬件温度'),

	load: function() {
		return fs.exec('/usr/bin/xgp-temps').then(function(r) {
			try {
				return JSON.parse(r.stdout);
			}
			catch (e) {
				return null;
			}
		}).catch(function() {
			return null;
		});
	},

	render: function(data) {
		var table = E('table', { 'class': 'table' });

		if (!data) {
			table.appendChild(E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td left', 'width': '100%' },
					_('温度采集器不可用（/usr/bin/xgp-temps）'))
			]));
			return table;
		}

		var rows = [];

		/* 处理器 / 图形处理器：单传感器直出 */
		rows.push([ _('处理器'), null,
			(data.cpu != null) ? tempNode(data.cpu) : dimNode('—') ]);
		rows.push([ _('图形处理器'), null,
			(data.gpu != null) ? tempNode(data.gpu) : dimNode('—') ]);

		/* 无线网卡：主行最高值 + 每 phy 明细 */
		var wifi = Array.isArray(data.wifi) ? data.wifi : [];
		var wmax = null, wi;
		for (wi = 0; wi < wifi.length; wi++)
			if (wmax == null || wifi[wi].temp > wmax)
				wmax = wifi[wi].temp;
		rows.push([ _('无线网卡') + (wifi.length ? '（%d）'.format(wifi.length) : ''), null,
			(wmax != null)
				? E('span', {}, [ tempNode(wmax), dimNode(wifi.length > 1 ? ' ' + _('最高') : '') ])
				: dimNode('—') ]);
		for (wi = 0; wi < wifi.length; wi++)
			rows.push([ wifi[wi].label, true, tempNode(wifi[wi].temp, true) ]);

		/* 5G 模组：主行最高值（附数据年龄）+ 每传感器明细 */
		var modem = (data.modem && Array.isArray(data.modem.sensors))
			? data.modem : null;
		var mmax = modem ? modem.max : null;
		var age = (data.modem_age != null) ? data.modem_age : 0;
		var mainVal;
		if (mmax != null) {
			var parts = [ tempNode(mmax) ];
			if (modem.sensors.length > 1)
				parts.push(dimNode(' ' + _('最高')));
			if (age > 15)
				parts.push(dimNode('（%ds 前，模组忙期）'.format(age)));
			mainVal = E('span', {}, parts);
		}
		else {
			mainVal = dimNode('—');
		}
		rows.push([ _('5G 模组') + (modem ? '（%d）'.format(modem.sensors.length) : ''), null, mainVal ]);
		if (modem)
			for (var mi = 0; mi < modem.sensors.length; mi++)
				rows.push([ modem.sensors[mi].label, true,
					tempNode(modem.sensors[mi].temp, true) ]);

		for (var ri = 0; ri < rows.length; ri++) {
			table.appendChild(E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td left', 'width': '55%',
					'style': rows[ri][1] ? DIM_STYLE : '' },
					[ rows[ri][0] ]),
				E('td', { 'class': 'td left' }, [ rows[ri][2] ])
			]));
		}

		return table;
	}
});
