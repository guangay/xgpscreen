include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-xgpscreen
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-xgpscreen
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=XGP V3 SPI screen (Python renderer + LuCI pages)
  DEPENDS:=+python3 +python3-pillow +kmod-fb-tft +ffmpeg +usbutils
  PKGARCH:=all
endef

define Package/luci-app-xgpscreen/description
  为 XGP V3 的 1.47 寸 SPI 屏（GC9307，320x172 可见区）提供 Python 渲染守护：
  信息页（时钟/日期/IP/温度/5G 模组/网速曲线等）、媒体页（图片/GIF/视频）、
  Python 代码页，以及 LuCI 的「页面设置 / 页面预览 / 媒体库」三页。
  与 LVGL 版 xgp-v3-screen 互斥，二者只能启用其一。
endef

define Package/luci-app-xgpscreen/conffiles
/etc/config/xgpscreen
endef

define Package/luci-app-xgpscreen/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) ./files/usr/bin/xgpscreen.py $(1)/usr/bin/
	$(INSTALL_BIN) ./files/usr/bin/xgp-temps $(1)/usr/bin/
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./files/etc/init.d/xgpscreen $(1)/etc/init.d/
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./files/etc/config/xgpscreen $(1)/etc/config/
	$(INSTALL_DIR) $(1)/usr/share/xgpscreen
	$(INSTALL_DATA) ./files/usr/share/xgpscreen/wqy-microhei.ttc $(1)/usr/share/xgpscreen/
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/controller/xgpmedia.lua $(1)/usr/lib/lua/luci/controller/
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/model/cbi/xgpmedia.lua $(1)/usr/lib/lua/luci/model/cbi/
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/view/xgpmedia
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/view/xgpmedia/upload.htm $(1)/usr/lib/lua/luci/view/xgpmedia/
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/view/xgpmedia/dvalue.htm $(1)/usr/lib/lua/luci/view/xgpmedia/
	$(INSTALL_DIR) $(1)/www/luci-static/resources/view
	$(INSTALL_DATA) ./files/www/luci-static/resources/view/xgpscreen.js $(1)/www/luci-static/resources/view/
	$(INSTALL_DATA) ./files/www/luci-static/resources/view/xgppages.js $(1)/www/luci-static/resources/view/
	$(INSTALL_DIR) $(1)/www/luci-static/resources/view/status/include
	$(INSTALL_DATA) ./files/www/luci-static/resources/view/status/include/25_xgp_temps.js $(1)/www/luci-static/resources/view/status/include/
	$(INSTALL_DIR) $(1)/usr/share/luci/menu.d
	$(INSTALL_DATA) ./files/usr/share/luci/menu.d/luci-app-xgpscreen.json $(1)/usr/share/luci/menu.d/
	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d
	$(INSTALL_DATA) ./files/usr/share/rpcd/acl.d/luci-app-xgpscreen.json $(1)/usr/share/rpcd/acl.d/
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
endef

define Build/Compile
endef

$(eval $(call BuildPackage,luci-app-xgpscreen))