from decimal import Decimal, InvalidOperation


# Разбирает одно- или двухзначное представление линии.
def parse_line_components(value: object) -> list[Decimal] | None:
	if value is None:
		return None

	parts = str(value).strip().split("/")
	if len(parts) not in (1, 2):
		return None

	try:
		values = [Decimal(part.strip()) for part in parts]
	except InvalidOperation:
		return None

	return values if all(part.is_finite() for part in values) else None


# Усредняет компоненты тотала с исходными знаками.
def normalize_total(value: object) -> Decimal | None:
	values = parse_line_components(value)
	if values is None:
		return None
	return sum(values, Decimal(0)) / len(values)


# Усредняет модуль форы и возвращает отрицательный знак при наличии.
def normalize_handicap(value: object) -> Decimal | None:
	values = parse_line_components(value)
	if values is None:
		return None

	handicap = sum((abs(part) for part in values), Decimal(0)) / len(values)
	return -handicap if any(part.is_signed() for part in values) else handicap
