# configs

- `weir.yaml`: gateway settings (models, kill switches, namespaces). Added in Task 7.
- `ablations/*.yaml`: overlays merged on top of `weir.yaml`, selected with `WEIR_ABLATION`.
- `tenants.yaml`: API-key tenants. Keys come from `.env`, never from this folder.
- `prices.yaml`: list prices with effective dates. Added in Task 9.
