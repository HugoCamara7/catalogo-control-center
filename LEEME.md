# Subir estos archivos

> Incluye la limpieza visual del modulo de solicitudes.
> Reemplaza a todos los ZIP anteriores.

Reemplaza a cualquier ZIP anterior.

## Reemplazar (2)
- `app_matrixify.py` → raíz
- `.streamlit/secrets.example.toml` → `.streamlit/secrets.example.toml`

## Agregar (9)
- `assets/app.css`
- `engines/__init__.py`, `engines/normalize.py`, `engines/excel_io.py`, `engines/audit.py`
- `scripts/test_engines_normalize.py`, `scripts/test_engines_excel_io.py`,
  `scripts/test_engines_audit.py`, `scripts/test_auth_accesos.py`
- `INVENTARIO_ARCHIVOS.md` → raíz

`engines/` es carpeta nueva. **Todo en un solo commit.**

---

## Lo primero que debes mirar al entrar

En la barra lateral, bajo las marcas permitidas, aparece un recuadro:

- **Verde "Almacenamiento persistente"** → `[ticketing]` está bien configurado.
  Las solicitudes y la auditoría se guardan en GitHub y sobreviven a los
  redespliegues. Puedo seguir con el panel de auditoría y la carga desde solicitud.

- **Naranja "Almacenamiento temporal"** → el backend sigue en `local`.
  Todo se borra en cada redespliegue. Revisa el bloque `[ticketing]` en
  Manage app → Settings → Secrets.

Dime de qué color sale.

---

## Paso obligatorio: contraseñas de los 8 comerciales

Sin esto no pueden entrar. En Manage app → Settings → Secrets:

```toml
[app_auth.users]
"hugo.camara@forus.pe"          = "TU_CLAVE"
"luis.nunez@forus.pe"           = "TU_CLAVE"
"comercial@forus.pe"            = "TU_CLAVE"
"alejandro.mosqueira@forus.pe"  = "TU_CLAVE"
"clara.gallastegui@forus.pe"    = "TU_CLAVE"
"natalia.ludowieg@forus.pe"     = "TU_CLAVE"
"daniela.ballon@forus.pe"       = "TU_CLAVE"
"mario.biggio@forus.pe"         = "TU_CLAVE"
"nicolas.rodriguez@forus.pe"    = "TU_CLAVE"
"alejandro.espinoza@forus.pe"   = "TU_CLAVE"
```

> Si defines `[app_auth.users]`, esa lista reemplaza por completo a la del
> código. Incluye a Hugo y Luis o quedan fuera.

---

## Qué revisar tras el despliegue

- [ ] Barra lateral: tu nombre y rol arriba (Hugo Camara / Administrador).
- [ ] Barra lateral: el recuadro de almacenamiento.
- [ ] Con un correo comercial: solo "Input comercial" y "Mis solicitudes".
- [ ] En "Mis solicitudes" de un comercial: 5 KPIs.
- [ ] Como Hugo: todo igual que antes.

## Volver atrás

GitHub → Commits → abre el commit → **Revert**.


---

## Limpieza visual de solicitudes (incluida)

| Antes | Ahora |
|---|---|
| 5 tarjetas blancas con solo un titulo y una frase, y los controles sueltos debajo | cabecera de una linea, pegada a su contenido |
| 10 tarjetas de KPI, 8 en cero | 5 agrupadas. Vencidos y fallidos solo aparecen si hay |
| Notificaciones abiertas con 20 filas de cambios internos | colapsadas, 8 mas recientes |
| `Job MOCK-6AAD... - in_progress - 0%` visible al cerrar | la barra desaparece al completarse |
| 4 metricas gigantes, una de ellas un correo truncado | 3 cifras compactas + archivo y responsable como texto |
| Tabla cruda con `processed, errors, closed_by, file_hash` | dentro de "Detalle tecnico del cierre" |

Ningun cambio toca reglas de negocio, permisos ni estados.
