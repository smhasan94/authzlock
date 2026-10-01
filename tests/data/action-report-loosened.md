<!-- authzlock -->
### authzlock: access-control changes

1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown

| Change | Methods | Path | View | Details |
|---|---|---|---|---|
| loosened | DELETE,GET | `invoices/<int:pk>/` | `billing.views.InvoiceDetailView` | `R2: custom class billing.permissions.IsOwner removed`<br>`permission_classes`: `[billing.permissions.IsOwner, rest_framework.permissions.IsAuthenticated]` → `[rest_framework.permissions.IsAuthenticated]` |

<details><summary>1 custom permission registry change</summary>

| Change | Class | Details |
|---|---|---|
| removed | `billing.permissions.IsOwner` |  |

</details>
