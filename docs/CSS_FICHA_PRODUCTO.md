# Separación de la ficha de producto (Hush Puppies y Rockford)

## Por qué se ve distinto en cada marca

El Body HTML que genera la app es **idéntico para las cuatro tiendas**. Está
comprobado: generando el mismo producto con las cuatro configuraciones de marca,
el HTML sale con el mismo sha256 y los mismos 503 caracteres.

```
columbia       sha=0eb3c51dee173556 len=503
hush_puppies   sha=0eb3c51dee173556 len=503
vans           sha=0eb3c51dee173556 len=503
rockford       sha=0eb3c51dee173556 len=503
```

Por lo tanto **el generador no es la causa**. La estructura que emite es:

```html
<section class="nweb" id="nombre-web-section">
  <div class="nweb__Descripcion"><h3 class="nweb__Descripcion-titulo">Descripción</h3><p>…</p></div>
  <div class="nweb__Caracteristicas"><h3 …>Características</h3><ul><li>…</li></ul></div>
  <div class="nweb__Materiales">…</div>
  <div class="nweb__Cuidados">…</div>
</section>
```

Ese HTML **no lleva estilos propios** — a propósito, porque el sanitizador de la
app (`catalog_rules.sanitize_body_html`) elimina cualquier `<style>` del cuerpo,
y un `style=` en línea le ganaría al tema y rompería las tiendas que hoy se ven
bien. O sea: **la separación la pone el tema de cada tienda**.

Columbia y Vans se ven bien porque sus temas ya estilan las clases `nweb__`.
Hush Puppies y Rockford no las tienen, así que caen en los márgenes por defecto
del tema: el bloque arranca pegado al borde y los títulos quedan encima del
texto.

**La corrección va en el tema de esas dos tiendas, no en la app.** Así Columbia
y Vans no se tocan.

## Qué pegar, y solo en Hush Puppies y Rockford

Shopify admin → **Tienda online → Temas → … → Editar código** →
`assets/base.css` (o el `.css` principal del tema), al final del archivo.

Si el tema tiene **Configuración → Custom CSS**, va ahí mejor: sobrevive a las
actualizaciones del tema.

```css
/* Ficha de producto generada por Catalog Control Center */
.nweb {
  display: block;
  margin-top: 1.5rem;
  padding-top: 0.5rem;
  line-height: 1.6;
}

.nweb > div + div {
  margin-top: 2rem;
}

.nweb h3 {
  margin: 0 0 0.75rem;
  font-size: 1.05rem;
  line-height: 1.3;
  font-weight: 600;
}

.nweb p {
  margin: 0 0 0.75rem;
}

.nweb p:last-child {
  margin-bottom: 0;
}

.nweb ul {
  margin: 0;
  padding-left: 1.25rem;
}

.nweb li {
  margin-bottom: 0.4rem;
}

.nweb li:last-child {
  margin-bottom: 0;
}
```

## Cómo comprobarlo

1. Abre una ficha de Rockford y una de Hush Puppies antes de pegar el CSS.
2. Pega el CSS y guarda.
3. Recarga con `Ctrl+F5`. Debe quedar aire entre Descripción, Características,
   Materiales y Cuidados, y el bloque ya no arranca pegado arriba.
4. Abre una de Columbia y una de Vans para confirmar que **no cambiaron**: no se
   tocó su tema.

## Si Hush Puppies sigue viéndose raro después del CSS

Entonces no es espaciado, es que esos productos tienen un **Body HTML heredado**
con otra estructura, de antes de este generador. Dos cosas:

- La app ya sabe detectarlos: `_body_needs_material_care_fix()` marca los
  cuerpos que traen Materiales/Cuidados sin las secciones `nweb__`.
- Se reparan con **Mantenimiento parcial → operación "body"** en modo
  `fix_sections`, que reconstruye el cuerpo respetando el texto existente.

Manda un pantallazo de una ficha de Hush Puppies con ese aspecto raro y se
confirma cuál de los dos casos es.
