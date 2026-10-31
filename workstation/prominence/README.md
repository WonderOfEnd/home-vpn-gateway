# Prominence II: Hasturian Era

Версии и параметры запуска — в instance-summary.json: v4.1.5hf, Minecraft 1.20.1,
Fabric Loader 0.19.3, Java 17, heap 6144 MiB. Для перевода квестов установлен
ftbquesttransl-1.20.1-fabric-1.4.0.jar.

29 октября запуск зависал в Estrogen CosmeticAPI на HTTP-запросе без таймаута.
В estrogen-5.0.8+1.20.1-fabric.jar изменена вложенная библиотека
META-INF/jars/resourceful-cosmetics-4j-1.0.5.jar, единственный класс
com/teamresourceful/resourcefulcosmetics/CosmeticsHttp.class.

AddCosmeticsTimeout.java добавляет HttpRequest.Builder.timeout на 8 секунд
в два HTTP builders GET/POST, проверяет ровно два изменения и копирует остальные
entries. Это исходник уже применённой локальной правки, а не новая версия мода.

Для воспроизведения собрать patcher с ASM 9, передать оригинальную вложенную
библиотеку и отдельный выходной путь, затем заменить только эту библиотеку
в копии внешнего JAR. Оригинал и миры сохранить отдельно. repair.json содержит
SHA-256 до/после; хеш установленного мода 31 октября совпал с sha256_after.

TestCosmeticsTimeout.java проверяет HTTP 200 и таймауты GET/POST на локальном
сервере. Для сборки нужны patched jar и его зависимости, для запуска — Java 17+.

Complementary Reimagined r5.9.3 и Iris 1.7.6 уже находятся в сборке. Шейдеры
включались с Medium 29 октября, затем после зависания выключены. Сохранённый
iris.properties отражает итог: shaderPack пуст, enableShaders=false.
Повторное зависание 30 октября произошло в Dota с YouTube; причина не установлена.
Этот репозиторий шейдеры автоматически не включает.

Обновление сборки может перезаписать исправление Estrogen. Перед повторным
применением проверить версию и исходный SHA-256; не применять патчер к уже
изменённой библиотеке. Бинарные JAR в репозиторий не включены.
