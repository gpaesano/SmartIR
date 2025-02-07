# round to given precision
@staticmethod
def precision_round(number, precision):
    if precision == 0.1:
        return round(float(number), 1)
    if precision == 0.5:
        return round((float(number) * 2) / 2.0, 1)
    elif precision == 1:
        return round(float(number))
    elif precision > 1:
        return round(float(number) / int(precision)) * int(precision)
    else:
        return None


@staticmethod
def closest_match_index(value, list):
    prev_val = None
    for index, entry in enumerate(list):
        if entry > (value or 0):
            if prev_val is None:
                return index
            diff_lo = value - prev_val
            diff_hi = entry - value
            if diff_lo < diff_hi:
                return index - 1
            return index
        prev_val = entry

    return len(list) - 1


@staticmethod
def closest_match_value(value, list):
    if value is None or not len(list):
        return None

    temp = sorted(
        list,
        key=lambda entry: abs(float(entry) - value),
    )
    if len(temp):
        return temp[0]
    else:
        return None
