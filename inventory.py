import csv
import sys
import readline
import shlex
from datetime import date
from pathlib import Path

import atexit



BASE_DIR = Path(__file__).resolve().parent
HISTORY_FILE = BASE_DIR / ".command_history"
TRANSACTIONS_FILE = BASE_DIR / "transactions.csv"
STOCK_FILE = BASE_DIR / "stock.csv"
PRODUCTION_FILE = BASE_DIR / "production.csv"
BOM_DIR = BASE_DIR / "bom"
ORDERED_FILE = BASE_DIR / "ordered.csv"
OPERATIONS_FILE = BASE_DIR / "operations.csv"




TODAY = date.today().isoformat()
FIELDS = [
    "date",
    "type",
    "component",
    "quantity",
    "unit_cost",
    "batch_id",
    "comment",
]


def init(source_file):
    source_path = BASE_DIR / source_file

    if TRANSACTIONS_FILE.exists():
        print("transactions.csv уже существует. Инициализация отменена.")
        return

    with source_path.open("r", encoding="utf-8-sig", newline="") as file:
        source_rows = list(csv.DictReader(file))

    transactions = []

    for row in source_rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue

        price = (row.get("price") or "").strip()

        transactions.append({
            "date": TODAY,
            "type": "add",
            "component": name,
            "quantity": row.get("stock", "0"),
            "unit_cost": price,
            "batch_id": "",
            "comment": f"Начальная инициализация из {source_path.name}",
        })

    with TRANSACTIONS_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(transactions)

    print(f"Создан transactions.csv: {len(transactions)} операций add")

def calculate_stock():
    stock = {}

    with TRANSACTIONS_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            component = (row.get("component") or "").strip()

            if not component:
                continue

            quantity = int(row["quantity"])

            if row["type"] == "add":
                unit_cost = (row.get("unit_cost") or "").strip()
                key = (component, unit_cost)
                stock.setdefault(key, 0)
                stock[key] += quantity

            elif row["type"] == "remove":
                remaining = quantity

                # Списываем из старых ценовых партий в первую очередь.
                for key in stock:
                    if key[0] != component or stock[key] <= 0:
                        continue

                    taken = min(stock[key], remaining)
                    stock[key] -= taken
                    remaining -= taken

                    if remaining == 0:
                        break

                if remaining > 0:
                    print(
                        f"Предупреждение: в журнале списано больше, "
                        f"чем было в наличии: {component}, "
                        f"не удалось списать {remaining} шт."
                    )

    return stock

def update_stock():
    stock = calculate_stock()
    rows = []
    component_order = []

    for (component, unit_cost), quantity in stock.items():
        if quantity <= 0:
            continue

        if component not in component_order:
            component_order.append(component)

    for component in component_order:
        for (name, unit_cost), quantity in stock.items():
            if name != component or quantity <= 0:
                continue

            rows.append({
                "component": name,
                "stock": quantity,
                "unit_cost": unit_cost,
            })

    with STOCK_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["component", "stock", "unit_cost"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Обновлён stock.csv: {len(rows)} строк")

def update_production():
    batches = {}

    with TRANSACTIONS_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            production_id = row["batch_id"]

            if not production_id:
                continue

            if production_id not in batches:
                batches[production_id] = {
                    "start": None,
                    "end": None,
                    "removals": [],
                }

            batch = batches[production_id]

            if row["type"] == "start_prod":
                batch["start"] = row

            elif row["type"] == "remove":
                batch["removals"].append(row)

            elif row["type"] == "end_prod":
                batch["end"] = row

    rows = []

    for production_id, batch in batches.items():
        start = batch["start"]
        end = batch["end"]

        # Пропускаем незавершённые партии.
        if start is None or end is None:
            continue

        quantity = int(start["quantity"])

        if quantity <= 0:
            continue

        total_cost = sum(
            float(row["quantity"]) * float(row["unit_cost"])
            for row in batch["removals"]
        )

        rows.append({
            "production_id": production_id,
            "date": start["date"],
            "device": start["component"],
            "quantity": quantity,
            "comment": start["comment"],
            "bom_file": f'{start["component"]}.csv',
            "total_cost": round(total_cost, 4),
            "unit_cost": round(total_cost / quantity, 4),
        })

    # Сортируем партии по номеру.
    rows.sort(key=lambda row: row["production_id"])

    with PRODUCTION_FILE.open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        fieldnames = [
            "production_id",
            "date",
            "device",
            "quantity",
            "comment",
            "bom_file",
            "total_cost",
            "unit_cost",
        ]

        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Обновлён production.csv: {len(rows)} партий")

def rename(component, newname):
    component = component.strip()
    newname = newname.strip()

    if not component or not newname:
        print("Ошибка: старое и новое имена обязательны.")
        return

    if component == newname:
        print("Старое и новое имена совпадают.")
        return

    files = [TRANSACTIONS_FILE, ORDERED_FILE]
    files.extend(BOM_DIR.glob("*.csv"))

    # Проверяем, не занято ли новое имя другим компонентом.
    for path in files:
        if not path.exists():
            continue

        try:
            with path.open(
                "r", encoding="utf-8-sig", newline=""
            ) as file:
                reader = csv.DictReader(file)

                if "component" not in (reader.fieldnames or []):
                    continue

                for row in reader:
                    if row.get("component") == newname:
                        print(
                            f"Ошибка: компонент {newname} "
                            f"уже существует в файле {path.name}."
                        )
                        return

        except (OSError, csv.Error) as error:
            print(f"Ошибка чтения {path.name}: {error}")
            return

    changed = 0

    # Переименовываем компонент во всех нужных файлах.
    for path in files:
        if not path.exists():
            continue

        try:
            with path.open(
                "r", encoding="utf-8-sig", newline=""
            ) as file:
                reader = csv.DictReader(file)
                fieldnames = reader.fieldnames or []
                rows = list(reader)

            if "component" not in fieldnames:
                continue

            file_changed = 0

            for row in rows:
                if row.get("component") == component:
                    row["component"] = newname
                    file_changed += 1

            if file_changed:
                with path.open(
                    "w", encoding="utf-8-sig", newline=""
                ) as file:
                    writer = csv.DictWriter(
                        file,
                        fieldnames=fieldnames,
                    )
                    writer.writeheader()
                    writer.writerows(rows)

                changed += file_changed
                print(
                    f"{path.name}: "
                    f"переименовано записей — {file_changed}"
                )

        except (OSError, csv.Error) as error:
            print(f"Ошибка обработки {path.name}: {error}")
            return

    if changed:
        print(
            f"Готово: {component} → {newname}. "
            f"Всего переименовано записей: {changed}."
        )
        update_stock()
    else:
        print(f"Компонент {component} не найден.")

def add(component, quantity, unit_cost, comment):
    component = component.strip()
    comment = comment.strip()

    if (
        not component
        or not str(quantity).strip()
        or not str(unit_cost).strip()
        or not comment
    ):
        print("Ошибка: все поля обязательны. Операция отменена.")
        return

    try:
        quantity = int(quantity)
        unit_cost = float(unit_cost)
    except ValueError:
        print("Ошибка: количество должно быть целым числом, цена — числом.")
        return

    if quantity <= 0 or unit_cost < 0:
        print("Ошибка: количество должно быть больше нуля, цена — неотрицательной.")
        return

    # Проверяем актуальные остатки по журналу транзакций.
    if TRANSACTIONS_FILE.exists():
        batches = calculate_stock()
    else:
        batches = {}

    existing_names = set()
    matching_price = False

    for (name, price), amount in batches.items():
        # Не учитываем партии, в которых ничего не осталось.
        if amount <= 0:
            continue

        if name == component:
            existing_names.add(name)

            if float(price) == unit_cost:
                matching_price = True

    # Определяем тип добавления до записи транзакции.
    if component not in existing_names:
        message = f"Добавлен новый компонент: {component}."
    elif matching_price:
        message = (
            f"Пополнена существующая партия: "
            f"{component}, цена {unit_cost}."
        )
    else:
        message = (
            f"Добавлена новая ценовая партия: "
            f"{component}, цена {unit_cost}."
        )

    transaction = {
        "date": TODAY,
        "type": "add",
        "component": component,
        "quantity": quantity,
        "unit_cost": unit_cost,
        "batch_id": "",
        "comment": comment,
    }

    # Записываем операцию в журнал.
    with TRANSACTIONS_FILE.open(
        "a",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writerow(transaction)

    print(f"{message} Количество: {quantity}.")

    # Автоматически обновляем остатки после успешного добавления.
    update_stock()

def ordered(component, quantity, order_id, total_cost, comment):
    component = component.strip()
    order_id = order_id.strip()
    comment = comment.strip()

    if not component or not order_id or not comment:
        print("Ошибка: компонент, номер заказа и комментарий обязательны.")
        return

    try:
        quantity = int(quantity)
    except ValueError:
        print("Ошибка: количество должно быть целым числом.")
        return

    if quantity <= 0:
        print("Ошибка: количество должно быть больше нуля.")
        return

    try:
        total_cost = float(total_cost)
    except ValueError:
        print("Ошибка: стоимость должна быть числом.")
        return

    if not 0 < total_cost < float("inf"):
        print("Ошибка: стоимость должна быть положительным конечным числом.")
        return

    unit_cost = total_cost / quantity

    fieldnames = [
        "date",
        "order_id",
        "component",
        "quantity",
        "total_cost",
        "unit_cost",
        "comment",
        "status",
        "received_date",
    ]

    if not ORDERED_FILE.exists():
        with ORDERED_FILE.open(
            "w", encoding="utf-8-sig", newline=""
        ) as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()

    try:
        with ORDERED_FILE.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)
            old_fieldnames = reader.fieldnames or []
            orders = list(reader)

        if any(row.get("order_id") == order_id for row in orders):
            print(f"Ошибка: номер заказа {order_id} уже существует.")
            return

        # Добавляем новые поля, сохраняя старые записи.
        for row in orders:
            row.setdefault("total_cost", "")
            row.setdefault("unit_cost", "")
            row.setdefault("status", "ordered")
            row.setdefault("received_date", "")

        # Обновляем заголовки, если структура CSV изменилась.
        if old_fieldnames != fieldnames:
            with ORDERED_FILE.open(
                "w", encoding="utf-8-sig", newline=""
            ) as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(orders)

        with ORDERED_FILE.open(
            "a", encoding="utf-8-sig", newline=""
        ) as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writerow({
                "date": TODAY,
                "order_id": order_id,
                "component": component,
                "quantity": quantity,
                "total_cost": total_cost,
                "unit_cost": unit_cost,
                "comment": comment,
                "status": "ordered",
                "received_date": "",
            })

    except (OSError, csv.Error) as error:
        print(f"Ошибка работы со списком заказов: {error}")
        return

    print(
        f"Заказ зарегистрирован: {component}, "
        f"{quantity} шт., общая стоимость {total_cost:.2f}, "
        f"цена за штуку {unit_cost:.2f}, ID {order_id}."
    )

def receive(order_id):
    order_id = order_id.strip()

    if not order_id:
        print("Ошибка: укажи номер заказа.")
        return

    if not ORDERED_FILE.exists():
        print("Список заказов пуст.")
        return

    try:
        with ORDERED_FILE.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)
            fieldnames = reader.fieldnames or []
            orders = list(reader)

        if not orders:
            print("Список заказов пуст.")
            return

        # Поддерживаем старый формат файла.
        for row in orders:
            row.setdefault("total_cost", "")
            row.setdefault("unit_cost", "")
            row.setdefault("status", "ordered")
            row.setdefault("received_date", "")

        fieldnames = [
            "date",
            "order_id",
            "component",
            "quantity",
            "total_cost",
            "unit_cost",
            "comment",
            "status",
            "received_date",
        ]

        matching = [
            row for row in orders
            if row["order_id"] == order_id
        ]

        if not matching:
            print(f"Заказ {order_id} не найден.")
            return

        if all(row["status"] == "received" for row in matching):
            print(f"Заказ {order_id} уже получен.")
            return

        # Отмечаем все строки этого заказа как полученные.
        for row in matching:
            row["status"] = "received"
            row["received_date"] = TODAY

        with ORDERED_FILE.open(
            "w", encoding="utf-8-sig", newline=""
        ) as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(orders)

        print(f"Заказ {order_id} отмечен как полученный.")

        for row in matching:
            print(f'  {row["component"]}: {row["quantity"]} шт.')

        print("\nПроверь полученные компоненты.")
        print("Если всё в порядке, внеси их на склад командой:")
        for row in matching:
            print(f'  add {row["component"]} {row["quantity"]} {row["unit_cost"]}')

    except (OSError, csv.Error) as error:
        print(f"Ошибка обработки заказа: {error}")

def remove(component, quantity, comment):
    component = component.strip()
    comment = comment.strip()

    if not component or not str(quantity).strip() or not comment:
        print("Ошибка: все поля обязательны. Операция отменена.")
        return

    try:
        quantity = int(quantity)
    except ValueError:
        print("Ошибка: количество должно быть целым числом.")
        return

    if quantity <= 0:
        print("Ошибка: количество должно быть больше нуля.")
        return

    if not TRANSACTIONS_FILE.exists():
        print("Ошибка: transactions.csv не найден.")
        return

    # Получаем актуальные остатки непосредственно из журнала.
    batches = calculate_stock()

    available = sum(
        amount
        for (name, price), amount in batches.items()
        if name == component and amount > 0
    )

    if available < quantity:
        print(
            f"Ошибка: недостаточно компонентов «{component}». "
            f"В наличии: {available}, требуется: {quantity}. "
            "Операция отменена."
        )
        return

    transaction = {
        "date": TODAY,
        "type": "remove",
        "component": component,
        "quantity": quantity,
        "unit_cost": "",
        "batch_id": "",
        "comment": comment,
    }

    # Записываем списание в журнал.
    with TRANSACTIONS_FILE.open(
        "a",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writerow(transaction)

    print(f"Списано: {component}, количество: {quantity}.")

    # Автоматически обновляем остатки после успешного списания.
    update_stock()

def bom(device):
    if not device or "/" in device or "\\" in device:
        print("Ошибка: укажи корректное название устройства.")
        return

    bom_file = BOM_DIR / f"{device}.csv"

    if not bom_file.is_file():
        print(f"Ошибка: BOM-файл не найден: {bom_file.name}")
        return

    try:
        with bom_file.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            required_fields = {"component", "quantity_per_device"}

            if not reader.fieldnames or not required_fields.issubset(
                reader.fieldnames
            ):
                print(
                    "Ошибка: в BOM должны быть колонки "
                    "'component' и 'quantity_per_device'."
                )
                return

            rows = list(reader)

    except OSError as error:
        print(f"Ошибка чтения BOM: {error}")
        return

    if not rows:
        print("BOM пуст.")
        return

    # Проверяем все строки до вывода состава.
    validated_rows = []

    for row in rows:
        component = (row.get("component") or "").strip()
        quantity = (row.get("quantity_per_device") or "").strip()

        if not component:
            print("Ошибка: в BOM есть строка без названия компонента.")
            return

        try:
            amount = float(quantity)
        except ValueError:
            print(
                f"Ошибка: некорректное количество компонента "
                f"«{component}»."
            )
            return

        if amount <= 0:
            print(
                f"Ошибка: количество компонента "
                f"«{component}» должно быть больше нуля."
            )
            return

        validated_rows.append((component, amount))

    print(f"\nСостав устройства: {device}")
    print("-" * 60)
    print(f"{'Компонент':40} {'На одно устройство':>18}")
    print("-" * 60)

    for component, amount in validated_rows:
        print(f"{component:40} {amount:>18g}")

    print("-" * 60)
    print(f"Всего позиций в BOM: {len(validated_rows)}")

def bomadd(device, component, quantity):
    if not device or "/" in device or "\\" in device:
        print("Ошибка: укажи корректное название устройства.")
        return

    component = component.strip()

    if not component:
        print("Ошибка: укажи название компонента.")
        return

    try:
        quantity = float(quantity)
    except ValueError:
        print("Ошибка: количество должно быть числом.")
        return

    if quantity <= 0:
        print("Ошибка: количество должно быть больше нуля.")
        return

    bom_file = BOM_DIR / f"{device}.csv"

    if not bom_file.is_file():
        print(f"Ошибка: BOM-файл не найден: {bom_file.name}")
        return

    try:
        with bom_file.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)

            if not reader.fieldnames or not {
                "component", "quantity_per_device"
            }.issubset(reader.fieldnames):
                print("Ошибка: некорректный формат BOM.")
                return

            rows = list(reader)

        found = False

        for row in rows:
            name = (row.get("component") or "").strip()

            if name == component:
                current = float(row["quantity_per_device"])
                row["quantity_per_device"] = str(current + quantity)
                found = True
                break

        if not found:
            rows.append({
                "component": component,
                "quantity_per_device": str(quantity),
            })

        with bom_file.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["component", "quantity_per_device"],
            )
            writer.writeheader()
            writer.writerows(rows)

    except (OSError, ValueError, KeyError, csv.Error) as error:
        print(f"Ошибка работы с BOM: {error}")
        return

    print(
        f"BOM {device}: компонент {component}, "
        f"добавлено {quantity:g}."
    )

def bomdel(device, component, quantity=None):
    if not device or "/" in device or "\\" in device:
        print("Ошибка: укажи корректное название устройства.")
        return

    component = component.strip()

    if not component:
        print("Ошибка: укажи название компонента.")
        return

    if quantity is not None:
        try:
            quantity = float(quantity)
        except ValueError:
            print("Ошибка: количество должно быть числом.")
            return

        if quantity <= 0:
            print("Ошибка: количество должно быть больше нуля.")
            return

    bom_file = BOM_DIR / f"{device}.csv"

    if not bom_file.is_file():
        print(f"Ошибка: BOM-файл не найден: {bom_file.name}")
        return

    try:
        with bom_file.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)

            if not reader.fieldnames or not {
                "component", "quantity_per_device"
            }.issubset(reader.fieldnames):
                print("Ошибка: некорректный формат BOM.")
                return

            rows = list(reader)

        updated_rows = []
        found = False

        for row in rows:
            name = (row.get("component") or "").strip()

            if name != component:
                updated_rows.append(row)
                continue

            if found:
                updated_rows.append(row)
                continue

            found = True

            if quantity is None:
                continue

            current = float(row["quantity_per_device"])
            remaining = current - quantity

            if remaining > 0:
                row["quantity_per_device"] = str(remaining)
                updated_rows.append(row)

        if not found:
            print(f"Ошибка: компонент {component} не найден в BOM.")
            return

        with bom_file.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["component", "quantity_per_device"],
            )
            writer.writeheader()
            writer.writerows(updated_rows)

    except (OSError, ValueError, KeyError, csv.Error) as error:
        print(f"Ошибка работы с BOM: {error}")
        return

    if quantity is None:
        print(f"BOM {device}: компонент {component} удалён.")
    else:
        print(
            f"BOM {device}: количество компонента {component} "
            f"уменьшено на {quantity:g}."
        )

def buy(device, count):
    if not device or "/" in device or "\\" in device:
        print("Ошибка: укажи корректное название устройства.")
        return

    try:
        count = int(count)
    except ValueError:
        print("Ошибка: количество устройств должно быть целым числом.")
        return

    if count <= 0:
        print("Ошибка: количество устройств должно быть больше нуля.")
        return

    bom_file = BOM_DIR / f"{device}.csv"

    if not bom_file.is_file():
        print(f"Ошибка: BOM-файл не найден: {bom_file.name}")
        return

    try:
        with bom_file.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            required_fields = {"component", "quantity_per_device"}

            if not reader.fieldnames or not required_fields.issubset(
                reader.fieldnames
            ):
                print("Ошибка: некорректный формат BOM.")
                return

            bom_rows = list(reader)

        with STOCK_FILE.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            required_fields = {"component", "stock"}

            if not reader.fieldnames or not required_fields.issubset(
                reader.fieldnames
            ):
                print("Ошибка: некорректный формат stock.csv.")
                return

            stock = {}

            for row in reader:
                component = row["component"]
                quantity = float(row["stock"])

                stock[component] = stock.get(component, 0) + quantity

        last_purchases = {}

        with TRANSACTIONS_FILE.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)

            required_fields = {
                "date", "type", "component", "unit_cost", "comment"
            }

            if not reader.fieldnames or not required_fields.issubset(
                reader.fieldnames
            ):
                print("Ошибка: некорректный формат transactions.csv.")
                return

            for row in reader:
                if row["type"] == "add":
                    last_purchases[row["component"]] = {
                        "unit_cost": float(row["unit_cost"]),
                        "comment": row["comment"],
                        "date": row["date"],
                    }

    except (OSError, csv.Error, ValueError, TypeError) as error:
        print(f"Ошибка чтения данных: {error}")
        return

    
    requirements = {}

    for row in bom_rows:
        component = (row.get("component") or "").strip()

        try:
            per_device = float(row["quantity_per_device"])
        except (ValueError, TypeError):
            print(f"Ошибка количества компонента «{component}» в BOM.")
            return

        if not component or per_device <= 0:
            print("Ошибка: BOM содержит некорректную позицию.")
            return

        requirements[component] = (
            requirements.get(component, 0) + per_device * count
        )

    # Считаем количество компонентов, которые уже заказаны и ещё не получены.
    ordered_stock = {}

    if ORDERED_FILE.exists():
        try:
            with ORDERED_FILE.open(
                "r", encoding="utf-8-sig", newline=""
            ) as file:
                reader = csv.DictReader(file)

                required_fields = {"component", "quantity"}

                if not reader.fieldnames or not required_fields.issubset(
                    reader.fieldnames
                ):
                    print("Ошибка: некорректный формат ordered.csv.")
                    return

                for row in reader:
                    # Учитываем только заказы, которые ещё не получены.
                    # Пустой статус поддерживает старые записи.
                    status = (row.get("status") or "ordered").strip()

                    if status != "ordered":
                        continue

                    component = (row.get("component") or "").strip()

                    try:
                        quantity = int(row["quantity"])
                    except (ValueError, TypeError):
                        print(
                            f"Ошибка количества в ordered.csv "
                            f"для компонента «{component}»."
                        )
                        return

                    if not component or quantity <= 0:
                        print("Ошибка: некорректная запись в ordered.csv.")
                        return

                    ordered_stock[component] = (
                        ordered_stock.get(component, 0) + quantity
                    )

        except (OSError, csv.Error) as error:
            print(f"Ошибка чтения ordered.csv: {error}")
            return

    shortages = []

    for component, required in requirements.items():
        available = stock.get(component, 0)
        ordered_quantity = ordered_stock.get(component, 0)

        missing = max(0, required - available - ordered_quantity)

        if available < required:
            purchase = last_purchases.get(component)

            shortages.append({
                "component": component,
                "required": required,
                "available": available,
                "ordered": ordered_quantity,
                "missing": missing,
                "purchase": purchase,
            })


    print(f"\nПлан закупки: {device}, {count} шт.")
    print()

    if not shortages:
        print("Всех компонентов достаточно для производства.")
        return

    headers = [
        "Название",
        "Есть",
        "Заказано",
        "Нужно",
        "Докупить",
        "Цена",
        "Стоимость",
        "Комментарий",
    ]

    table = []
    estimated_total = 0
    known_prices = True

    for item in shortages:
        purchase = item["purchase"]

        if purchase is None:
            price = "—"
            comment = "нет данных"
            cost = "—"
            known_prices = False
        else:
            price = f'{purchase["unit_cost"]:g}'
            comment = purchase["comment"] or "—"
            cost_value = item["missing"] * purchase["unit_cost"]
            cost = f"{cost_value:.2f}"
            estimated_total += cost_value

        table.append([
            item["component"],
            f'{item["available"]:g}',
            f'{item["ordered"]:g}',
            f'{item["required"]:g}',
            f'{item["missing"]:g}',
            price,
            cost,
            comment,
        ])

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in table))
        for i in range(len(headers))
    ]

    def format_row(row):
        return " | ".join(
            value.ljust(widths[i])
            for i, value in enumerate(row)
        )

    print(format_row(headers))
    print("-+-".join("-" * width for width in widths))

    for row in table:
        print(format_row(row))

    print()

    if known_prices:
        print(f"Примерная стоимость закупки: {estimated_total:.2f}")
    else:
        print(
            "Примерная стоимость закупки не рассчитана полностью: "
            "нет цены для некоторых компонентов."
        )
  
def make(device, count, comment):
    # Проверяем количество устройств.
    try:
        count = int(count)
    except (ValueError, TypeError):
        print("Ошибка: количество устройств должно быть целым числом.")
        return

    if count <= 0:
        print("Ошибка: количество устройств должно быть больше нуля.")
        return

    comment = (comment or "").strip()
    device = (device or "").strip()

    if not comment:
        print("Ошибка: укажи комментарий к производственной партии.")
        return

    if not TRANSACTIONS_FILE.is_file():
        print("Ошибка: журнал transactions.csv не найден.")
        return

    if not device or "/" in device or "\\" in device:
        print("Ошибка: укажи корректное название устройства.")
        return

    bom_file = BOM_DIR / f"{device}.csv"

    if not bom_file.is_file():
        print(f"Ошибка: BOM-файл не найден: {bom_file.name}")
        return

    # Читаем и проверяем BOM.
    try:
        with bom_file.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)
            required_fields = {"component", "quantity_per_device"}

            if not reader.fieldnames or not required_fields.issubset(
                reader.fieldnames
            ):
                print("Ошибка: некорректные колонки BOM.")
                return

            rows = list(reader)

    except (OSError, csv.Error) as error:
        print(f"Ошибка чтения BOM: {error}")
        return

    if not rows:
        print("Ошибка: BOM пуст.")
        return

    # Рассчитываем потребность в компонентах.
    requirements = {}

    for row in rows:
        component = (row.get("component") or "").strip()
        quantity = (row.get("quantity_per_device") or "").strip()

        if not component:
            print("Ошибка: в BOM есть строка без названия компонента.")
            return

        try:
            amount = float(quantity)
        except (ValueError, TypeError):
            print(f"Ошибка: некорректное количество «{component}».")
            return

        if not amount > 0 or not __import__("math").isfinite(amount):
            print(
                f"Ошибка: количество «{component}» должно быть "
                "положительным конечным числом."
            )
            return

        total = amount * count

        if not total.is_integer():
            print(
                f"Ошибка: количество «{component}» для этой партии "
                "должно быть целым числом."
            )
            return

        requirements[component] = (
            requirements.get(component, 0) + int(total)
        )

    # Сохраняем исходные байты журнала для возможного отката.
    try:
        old_transactions = TRANSACTIONS_FILE.read_bytes()
    except OSError as error:
        print(f"Ошибка чтения transactions.csv: {error}")
        return

    # Получаем остатки из журнала.
    try:
        stock = calculate_stock()
    except (OSError, csv.Error, ValueError, KeyError) as error:
        print(f"Ошибка расчёта остатков: {error}")
        return

    # Подготавливаем ценовые партии в порядке FIFO.
    available = {}

    for (component, price), quantity in stock.items():
        if quantity <= 0:
            continue

        try:
            unit_cost = float(price)
        except (ValueError, TypeError):
            print(
                f"Ошибка: у компонента «{component}» "
                f"некорректная цена «{price}»."
            )
            return

        if not __import__("math").isfinite(unit_cost) or unit_cost < 0:
            print(
                f"Ошибка: у компонента «{component}» "
                "некорректная цена."
            )
            return

        available.setdefault(component, []).append(
            [unit_cost, quantity]
        )

    # Проверяем наличие всех компонентов до изменения журнала.
    for component, required in requirements.items():
        batches = available.get(component, [])
        total_available = sum(quantity for _, quantity in batches)

        if total_available < required:
            print(
                f"Недостаточно «{component}»: "
                f"нужно {required}, в наличии {total_available}."
            )
            return

    # Планируем списания по FIFO с фиксацией фактической цены.
    planned_removals = []

    for component, required in requirements.items():
        remaining = required

        for price, quantity in available[component]:
            if remaining <= 0:
                break

            consumed = min(remaining, quantity)

            if consumed > 0:
                planned_removals.append({
                    "component": component,
                    "quantity": consumed,
                    "unit_cost": format(price, ".15g"),
                })
                remaining -= consumed

        if remaining != 0:
            print(
                f"Ошибка планирования FIFO для «{component}»: "
                f"не удалось распределить {remaining} шт."
            )
            return

    # Определяем следующий ID.
    # Проверяем журнал и старый production.csv, если он существует.
    numbers = []

    try:
        with TRANSACTIONS_FILE.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            if not reader.fieldnames or not set(FIELDS).issubset(
                reader.fieldnames
            ):
                print("Ошибка: некорректные колонки transactions.csv.")
                return

            for row in reader:
                batch_id = (row.get("batch_id") or "").strip()

                if batch_id.startswith("P") and batch_id[1:].isdigit():
                    numbers.append(int(batch_id[1:]))

    except (OSError, csv.Error) as error:
        print(f"Ошибка чтения transactions.csv: {error}")
        return

    production_file = BASE_DIR / "production.csv"

    if production_file.is_file():
        try:
            with production_file.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as file:
                reader = csv.DictReader(file)

                for row in reader:
                    for value in row.values():
                        value = (value or "").strip()

                        if value.startswith("P") and value[1:].isdigit():
                            numbers.append(int(value[1:]))

        except (OSError, csv.Error) as error:
            print(f"Ошибка чтения production.csv: {error}")
            return

    production_id = f"P{max(numbers, default=0) + 1:04d}"

    # Формируем всю операцию в памяти.
    transaction_rows = [{
        "date": TODAY,
        "type": "start_prod",
        "component": device,
        "quantity": count,
        "unit_cost": "",
        "batch_id": production_id,
        "comment": comment,
    }]

    for removal in planned_removals:
        transaction_rows.append({
            "date": TODAY,
            "type": "remove",
            "component": removal["component"],
            "quantity": removal["quantity"],
            "unit_cost": removal["unit_cost"],
            "batch_id": production_id,
            "comment": comment,
        })

    transaction_rows.append({
        "date": TODAY,
        "type": "end_prod",
        "component": device,
        "quantity": count,
        "unit_cost": "",
        "batch_id": production_id,
        "comment": comment,
    })

    # Записываем операцию и проверяем её после записи.
    try:
        with TRANSACTIONS_FILE.open(
            "a",
            encoding="utf-8",
            newline="",
        ) as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writerows(transaction_rows)
            file.flush()

            # Просим ОС передать данные файловой системе.
            import os
            os.fsync(file.fileno())

        # Повторно читаем журнал.
        with TRANSACTIONS_FILE.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            journal = list(csv.DictReader(file))

        batch_rows = [
            row for row in journal
            if (row.get("batch_id") or "").strip() == production_id
        ]

        starts = [
            (index, row) for index, row in enumerate(batch_rows)
            if row["type"] == "start_prod"
        ]
        ends = [
            (index, row) for index, row in enumerate(batch_rows)
            if row["type"] == "end_prod"
        ]

        if len(starts) != 1 or len(ends) != 1:
            raise ValueError(
                "Для партии должно быть ровно по одному "
                "start_prod и end_prod."
            )

        start_index, start = starts[0]
        end_index, end = ends[0]

        if start_index != 0 or end_index != len(batch_rows) - 1:
            raise ValueError(
                "Маркеры start_prod/end_prod стоят не на своих местах."
            )

        for marker in (start, end):
            if (
                marker["component"] != device
                or int(marker["quantity"]) != count
                or marker["comment"] != comment
            ):
                raise ValueError("Данные маркера производства не совпадают.")

        expected_removals = [
            (
                row["component"],
                int(row["quantity"]),
                row["unit_cost"],
            )
            for row in transaction_rows
            if row["type"] == "remove"
        ]

        actual_removals = [
            (
                row["component"],
                int(row["quantity"]),
                row["unit_cost"],
            )
            for row in batch_rows
            if row["type"] == "remove"
        ]

        if actual_removals != expected_removals:
            raise ValueError(
                "Списания в журнале не совпадают с планом FIFO."
            )

        for row in batch_rows:
            if row["comment"] != comment:
                raise ValueError("Комментарий партии не совпадает.")

    except (OSError, csv.Error, ValueError, KeyError, TypeError) as error:
        # Откатываем журнал к исходным байтам.
        try:
            TRANSACTIONS_FILE.write_bytes(old_transactions)
        except OSError as rollback_error:
            print(
                "КРИТИЧЕСКАЯ ОШИБКА: не удалось восстановить журнал. "
                "Не запускай новые операции, пока не проверишь "
                "transactions.csv."
            )
            print(f"Ошибка отката: {rollback_error}")
            return

        print(f"Ошибка записи или проверки производства: {error}")
        print("Журнал восстановлен до исходного состояния.")
        return

    try:
        update_production()
    except (OSError, csv.Error, ValueError, KeyError) as error:

        print(

            f"\nВНИМАНИЕ: производство {production_id} записано, "

            "но не удалось обновить production.csv."

        )

        print(f"Ошибка обновления производства: {error}")

        print("Повтори команду production для пересчёта производства.")

        return

    try:
        update_stock()
    except (OSError, csv.Error) as error:
        print(
            f"\nВНИМАНИЕ: производство {production_id} записано, "
            "но не удалось обновить stock.csv."
        )
        print(f"Ошибка обновления остатков: {error}")
        print("Повтори команду stock для пересчёта остатков.")
        return

    print(f"\nПроизводственная операция записана: {production_id}")
    print(f"Устройство: {device}")
    print(f"Количество: {count}")
    print(f"Событий записано: {len(transaction_rows)}")
    print(f"Комментарий: {comment}")
    print("FIFO и цены списания проверены.")
    print("stock.csv автоматически обновлён.")

def undo_transaction(transaction_type):
    if not TRANSACTIONS_FILE.exists():
        print("Ошибка: transactions.csv не найден.")
        return

    try:
        with TRANSACTIONS_FILE.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)
            fieldnames = reader.fieldnames
            transactions = list(reader)

        if not fieldnames or not transactions:
            print("Транзакции для отмены не найдены.")
            return

        # Отменяем только последнюю транзакцию.
        index = len(transactions) - 1
        transaction = transactions[index]

        # --------------------------------------------------
        # ОТМЕНА ПРОИЗВОДСТВА
        # --------------------------------------------------
        if transaction_type == "make":
            if transaction["type"] != "end_prod":
                print(
                    "Отмена производства невозможна: "
                    "последняя запись не end_prod."
                )
                return

            production_id = (
                transaction.get("batch_id") or ""
            ).strip()

            if not production_id:
                print(
                    "Ошибка: у последней записи нет batch_id."
                )
                return

            # Находим все записи последней производственной партии.
            batch_indices = [
                i for i, row in enumerate(transactions)
                if (row.get("batch_id") or "").strip()
                == production_id
            ]

            if not batch_indices:
                print("Ошибка: записи производственной партии не найдены.")
                return

            # Партия должна занимать непрерывный блок журнала.
            first = batch_indices[0]
            last = batch_indices[-1]

            if batch_indices != list(range(first, last + 1)):
                print(
                    "Отмена невозможна: записи партии "
                    "не образуют непрерывный блок."
                )
                return

            batch = transactions[first:last + 1]

            # Проверяем границы и типы записей.
            if (
                batch[0]["type"] != "start_prod"
                or batch[-1]["type"] != "end_prod"
            ):
                print(
                    "Ошибка: у производственной партии "
                    "некорректные границы."
                )
                return

            if any(
                row["type"] not in {"start_prod", "remove", "end_prod"}
                for row in batch
            ):
                print(
                    "Ошибка: в производственной партии "
                    "обнаружен неизвестный тип записи."
                )
                return

            if sum(
                row["type"] == "start_prod" for row in batch
            ) != 1 or sum(
                row["type"] == "end_prod" for row in batch
            ) != 1:
                print(
                    "Ошибка: партия должна содержать ровно "
                    "один start_prod и один end_prod."
                )
                return

            start = batch[0]
            end = batch[-1]

            # Сверяем маркеры производства.
            for key in ("component", "quantity", "comment", "date"):
                if start[key] != end[key]:
                    print(
                        "Ошибка: данные start_prod и end_prod "
                        f"различаются в поле {key}."
                    )
                    return

            device = start["component"]
            count = start["quantity"]
            comment = start.get("comment", "")
            date = start["date"]

            try:
                if int(count) <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                print("Ошибка: некорректное количество устройств.")
                return

            # Формируем команду повторного производства.
            restore_comment = f"{comment} {date}".strip()
            restore_command = (
                f'make {device} {count} "{restore_comment}"'
            )

            # Удаляем всю партию одним блоком.
            del transactions[first:last + 1]

            with TRANSACTIONS_FILE.open(
                "w", encoding="utf-8-sig", newline=""
            ) as file:
                writer = csv.DictWriter(
                    file, fieldnames=fieldnames
                )
                writer.writeheader()
                writer.writerows(transactions)

            print(
                f"Отменено производство {production_id}: "
                f"{device}, {count} шт. (от {date})."
            )

            # Пересчитываем оба производных журнала.
            update_production()
            update_stock()

            print("\nДля повторного производства выполни:")
            print(restore_command)
            return

        # --------------------------------------------------
        # ОТМЕНА ADD / REMOVE
        # --------------------------------------------------
        if transaction["type"] != transaction_type:
            print(
                f"Отмена невозможна: последняя транзакция — "
                f"{transaction['type']}, "
                f"а запрошена отмена {transaction_type}."
            )
            return

        comment = transaction.get("comment", "")
        date = transaction["date"]
        restore_comment = f"{comment} {date}".strip()

        if transaction_type == "add":
            restore_command = (
                f'add {transaction["component"]} '
                f'{transaction["quantity"]} '
                f'{transaction["unit_cost"]} '
                f'"{restore_comment}"'
            )
        elif transaction_type == "remove":
            restore_command = (
                f'remove {transaction["component"]} '
                f'{transaction["quantity"]} '
                f'"{restore_comment}"'
            )
        else:
            print(
                f"Неизвестный тип отмены: {transaction_type}."
            )
            return

        del transactions[index]

        with TRANSACTIONS_FILE.open(
            "w", encoding="utf-8-sig", newline=""
        ) as file:
            writer = csv.DictWriter(
                file, fieldnames=fieldnames
            )
            writer.writeheader()
            writer.writerows(transactions)

        print(
            f'Отменена транзакция {transaction_type}: '
            f'{transaction["component"]}, '
            f'{transaction["quantity"]} шт. '
            f'(от {date}).'
        )

        update_stock()

        print("\nДля восстановления записи выполни:")
        print(restore_command)

    except (OSError, csv.Error, KeyError) as error:
        print(f"Ошибка отмены транзакции: {error}")

def complete_component(text, state):
    """Автодополнение компонентов из транзакций и BOM-файлов."""
    components = set()

    # Компоненты из истории транзакций.
    try:
        with TRANSACTIONS_FILE.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            for row in csv.DictReader(file):
                if row.get("type") not in {"add", "remove"}:
                    continue

                component = (row.get("component") or "").strip()
                if component:
                    components.add(component)
    except (OSError, csv.Error):
        pass

    # Компоненты из всех BOM-файлов.
    try:
        for bom_file in BOM_DIR.glob("*.csv"):
            with bom_file.open(
                "r", encoding="utf-8-sig", newline=""
            ) as file:
                for row in csv.DictReader(file):
                    component = (row.get("component") or "").strip()
                    if component:
                        components.add(component)
    except (OSError, csv.Error):
        pass

    matches = sorted(
        (
            component
            for component in components
            if component.lower().startswith(text.lower())
        ),
        key=str.lower,
    )

    return matches[state] if state < len(matches) else None

def complete_bom(text, state):
    """Автодополнение названий BOM из папки bom."""
    try:
        names = sorted({
            path.stem
            for path in BOM_DIR.glob("*.csv")
            if path.stem.lower().startswith(text.lower())
        })
    except OSError:
        names = []

    return names[state] if state < len(names) else None

def complete_order(text, state):
    """Автодополнение ID активных заказов с комментариями."""
    try:
        with ORDERED_FILE.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            orders = csv.DictReader(file)
            matches = [
                row for row in orders
                if row["order_id"].lower().startswith(text.lower())
            ]
    except (OSError, csv.Error, KeyError):
        matches = []

    if state == 0 and matches:
        print()
        for row in matches:
            print(
                f'{row["order_id"]} — {row["component"]}, '
                f'{row["quantity"]} шт. — {row["comment"]}'
            )
        print(f'> receive {text}', end="", flush=True)

    return matches[state]["order_id"] if state < len(matches) else None

def tab_complete(text, state):
    """Автодополнение команд и их аргументов."""
    line = readline.get_line_buffer()
    parts = line.split()

    #print(f"\nDEBUG line={line!r}, parts={parts!r}, text={text!r}")

    commands = [
        "add", "remove", "rename", "ordered", "receive", "bom",
        "bomadd", "bomdel", "make", "buy", "stock", "production", "init",
        "quit",
    ]

    # Автодополнение самих команд
    if not parts or (len(parts) == 1 and not line.endswith(" ")):
        matches = [
            command for command in commands
            if command.startswith(text.lower())
        ]
        return matches[state] if state < len(matches) else None

    # Автодополнение компонентов
    if parts[0] in {"ordered", "add", "remove", "rename"} and len(parts) <= 2:
        return complete_component(text, state)

    # BOMADD / BOMDEL
    if parts[0] in {"bomadd", "bomdel"}:
        if len(parts) == 1:
            return complete_bom(text, state)
        elif len(parts) == 2:
            if line.endswith(" "):
                return complete_component(text, state)
            else:
                return complete_bom(text, state)
        elif len(parts) == 3:
            return complete_component(text, state)

    # Автодополнение названий BOM
    if parts[0] in {"buy", "make", "bom"} and len(parts) <= 2:
        return complete_bom(text, state)

    # Автодополнение активных заказов                           
    if parts[0] == "receive" and len(parts) <= 2:
        return complete_order(text, state)

    return None

def ensure_data_files():
    """Создаёт отсутствующие CSV-файлы с заголовками."""

    files = {
        TRANSACTIONS_FILE: FIELDS,
        STOCK_FILE: ["component", "stock", "unit_cost"],
        ORDERED_FILE: [
            "date",
            "order_id",
            "component",
            "quantity",
            "total_cost",
            "unit_cost",
            "comment",
            "status",
            "received_date",
        ],
        PRODUCTION_FILE: [
            "production_id",
            "date",
            "device",
            "quantity",
            "comment",
            "bom_file",
            "total_cost",
            "unit_cost",
        ],
    }

    for path, fieldnames in files.items():
        if path.exists():
            continue

        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(fieldnames)

        print(f"Создан файл {path.name}")


def main():
    ensure_data_files()
    print(  "Учёт компонентов. Команды: " 
            "add, remove, rename, bom, ordered, receive, bomadd, bomdel, undo, stock, make, buy, quit"
            )

    try:
        readline.read_history_file(HISTORY_FILE)
    except FileNotFoundError:
        pass
    atexit.register(readline.write_history_file, HISTORY_FILE)

    readline.parse_and_bind("tab: complete")
    readline.set_completer(tab_complete)

    while True:
        try:
            command = input("> ").strip()

            if not command:
                continue

            if command == "quit":
                break

            try:
                parts = shlex.split(command)
            except ValueError as e:
                print(f"Ошибка разбора команды: {e}")
                continue

            if parts[0] == "add":
                if len(parts) != 5:
                    print('Формат: add COMPONENT QUANTITY UNIT_COST "COMMENT"')
                    continue

                add(parts[1], parts[2], parts[3], parts[4])

            elif parts[0] == "remove":
                if len(parts) != 4:
                    print('Формат: remove COMPONENT QUANTITY "COMMENT"')
                    continue

                remove(parts[1], parts[2], parts[3])

            elif parts[0] == "bom":
                if len(parts) != 2:
                    print("Формат: bom DEVICE")
                    continue
                bom(parts[1])

            elif parts[0] == "bomadd":
                if len(parts) != 4:
                    print("Формат: bomadd DEVICE COMPONENT QUANTITY")
                    continue

                bomadd(parts[1], parts[2], parts[3])

            elif parts[0] == "bomdel":
                if len(parts) not in (3, 4):
                    print("Формат: bomdel DEVICE COMPONENT [QUANTITY]")
                    continue

                quantity = parts[3] if len(parts) == 4 else None
                bomdel(parts[1], parts[2], quantity)

            elif parts[0] == "make":
                if len(parts) != 4:
                    print('Формат: make DEVICE COUNT "COMMENT"')
                    continue
                make(parts[1], parts[2], parts[3])

            elif parts[0] == "buy":
                if len(parts) != 3:
                    print("Формат: buy DEVICE COUNT")
                    continue

                buy(parts[1], parts[2])

            elif parts[0] == "rename":
                if len(parts) != 3:
                    print("Формат: rename DEVICE NEWNAME")
                    continue

                rename(parts[1], parts[2])

            elif command == "stock":
                update_stock()

            elif parts[0] == "ordered":
                if len(parts) != 6:
                    print(
                        'Формат: ordered COMPONENT QUANTITY '
                        'ORDER_ID TOTAL_COST "COMMENT"'
                    )
                    continue
                ordered(parts[1],parts[2],parts[3],parts[4],parts[5],)

            elif parts[0] == "receive":
                if len(parts) != 2:
                    print("Формат: receive ORDER_ID")
                    continue

                receive(parts[1])

            elif parts[0] == "undo":
                if len(parts) != 2:
                    print("Формат: undo add | undo remove | undo make")
                    continue

                if parts[1] not in ("add", "remove", "make"):
                    print("Пока доступны: undo add, undo remove")
                    continue

                undo_transaction(parts[1])
                continue

            elif command == "production":
                update_production()

            elif command.startswith("init "):
                args = command.split(maxsplit=1)
                init(args[1])

            else:
                print("Неизвестная команда.")

        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break



if __name__ == "__main__":
    main()
