# Настройки ПК

Сохранены исходники существующих доработок; при загрузке репозитория они
автоматически не применяются.

## pcstate

Скрипт сохраняет список приложений, папки Konsole и имена работающих ВМ каждые
15 секунд. При следующем входе выбирается наиболее полный снимок за последнюю
минуту сеанса. `pcstate restore` запускает приложения и ВМ из него.

```sh
install -Dm755 pcstate/pcstate ~/.local/bin/pcstate
mkdir -p ~/.config/systemd/user ~/.local/share/applications
cp pcstate/systemd/pcstate-* ~/.config/systemd/user/
cp desktop/pcstate-restore.desktop ~/.local/share/applications/
systemctl --user daemon-reload
systemctl --user enable --now pcstate-session.service pcstate-snapshot.timer
```

`~/.local/bin` должен входить в PATH сеанса. «Вернуть состояние» находится в
меню приложений; ярлык на рабочий стол намеренно не ставится.

Скрипт не сохраняет RAM приложений и точную геометрию окон. Браузер восстанавливает
вкладки сам. pcstate-root.sh — ранее подготовленная настройка libvirt-guests:
suspend при выключении, ON_BOOT=ignore. Её применение и фактическое
усыпление/возобновление ВМ при этой сверке не проверялись.
Личные снимки из ~/.local/state/pcstate в Git не включаются.

## Prism

В `desktop/org.prismlauncher.PrismLauncher.desktop.in` заменить PRISM_DIR placeholder
на полный путь к portable Prism, сохранить без .in в ~/.local/share/applications/.
Поле Path нужно сохранить: скрипт portable-версии проверяет portable.txt относительно
рабочего каталога. Категория — Game.

## Prominence

Сведения о версиях и исходники исправления находятся в
[prominence/README.md](prominence/README.md). Моды и сохранения не публикуются.
