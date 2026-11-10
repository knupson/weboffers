#!/bin/sh
# 07/11 medido: al recrear el contenedor quedan SingletonLock/Socket/Cookie del hostname anterior y Chrome
# arranca sin abrir el CDP (cree el perfil en uso por otra máquina). Se borran antes de lanzar Chrome.
P=/config/chrome-profile
rm -f "$P/SingletonLock" "$P/SingletonSocket" "$P/SingletonCookie"
echo "chrome-init: candados del perfil borrados"
