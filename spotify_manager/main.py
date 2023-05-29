"""Interface file."""


# UFI
from spotify_manager.routines.monthly_routine import run_monthly_routines


if __name__ == "__main__":
    run_monthly_routines()
    print("Done!")
