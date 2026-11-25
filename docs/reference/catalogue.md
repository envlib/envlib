# Catalogue

::: envlib.catalogue.Catalogue
    options:
      show_root_heading: true

::: envlib.catalogue.DatasetRef
    options:
      show_root_heading: true

::: envlib.catalogue.validate_dataset
    options:
      show_root_heading: true

## Matching on plain data

`Catalogue.query()` and `Catalogue.distinct()` are these functions over the catalogue's entries. They
take catalogue `user_meta` dicts (`DatasetRef.metadata`), so a service that holds the entries
elsewhere (the envlib EDR API reads them from MongoDB) matches them by the same rules.

::: envlib.catalogue.match_entries
    options:
      show_root_heading: true

::: envlib.catalogue.latest_per_dataset
    options:
      show_root_heading: true

::: envlib.catalogue.distinct_values
    options:
      show_root_heading: true

::: envlib.catalogue.version_key
    options:
      show_root_heading: true
