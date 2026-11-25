"""Match existing Elefant CSV rows to Goodreads."""
from enrich_bookzone_goodreads import main


if __name__ == "__main__":
    main(
        default_input="data/carti_elefant.csv",
        default_output="data/carti_elefant.csv",
        default_min_delay=3.0,
        default_max_delay=8.0,
        default_batch_pause=(60.0, 120.0),
        goodreads_block_waits=(300, 600),
    )
