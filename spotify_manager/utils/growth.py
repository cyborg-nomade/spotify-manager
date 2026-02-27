"""Growth calculations."""


def calculate_growth(new_value: int, old_value: int) -> float:
    """Calculate growth rate (%)."""
    return ((new_value - old_value) / (old_value or 1)) * 100
