import fs from "node:fs/promises";
import path from "node:path";

const artifactToolModule = process.env.ARTIFACT_TOOL_PATH || "@oai/artifact-tool";
const { SpreadsheetFile, Workbook } = await import(artifactToolModule);

const outputDir = process.argv[2] || "outputs";
const outputName = process.argv[3] || process.env.CATALOG_TEMPLATE_OUTPUT_NAME || "formato_input_catalog_control_center.xlsx";
const outputPath = path.join(outputDir, outputName);

const inputColumns = [
  ["Mod-Col", "Identificacion", "SI", "Codigo modelo-color. Ej: 2092991-NRY", "2092991-NRY"],
  ["Codigo modelo", "Campo tecnico autogenerado", "NO", "La app lo puede obtener desde Mod-Col/ARTI. No lo llena la marca.", "2092991"],
  ["Codigo color", "Campo tecnico autogenerado", "NO", "La app lo puede obtener desde Mod-Col/ARTI. No lo llena la marca.", "NRY"],
  ["Marca", "Marca y clasificacion", "SI", "Marca destino.", "Columbia"],
  ["Genero", "Marca y clasificacion", "SI", "Hombre, Mujer, Unisex, Nino, Nina.", "Mujer"],
  ["Categoria", "Marca y clasificacion", "SI", "Calzado, Vestuario o Accesorios.", "Vestuario"],
  ["Sub Categoria", "Marca y clasificacion", "NO", "Subcategoria comercial.", "Casacas"],
  ["Tipo de prenda", "Marca y clasificacion", "SI", "Tipo pluralizado para Shopify.", "Casacas"],
  ["Color web", "Marca y clasificacion", "SI", "Nombre visible del color.", "Negro"],
  ["Title", "Descripcion y contenido", "SI", "Nombre comercial final.", "Casaca Impermeable Mujer Arcadia II"],
  ["Body HTML", "Descripcion y contenido", "NO", "HTML final si ya viene armado.", ""],
  ["Descripcion", "Descripcion y contenido", "NO", "Descripcion base.", "Casaca impermeable y respirable para lluvia."],
  ["Caracteristicas", "Descripcion y contenido", "NO", "Beneficios principales.", "Costuras selladas; capucha ajustable"],
  ["Materiales", "Descripcion y contenido", "NO", "Composicion/materialidad.", "100% poliester"],
  ["Cuidados", "Descripcion y contenido", "NO", "Instrucciones de cuidado.", "Lavar con agua fria; no usar lejia"],
  ["Talla", "Campo tecnico autogenerado", "SI", "La app la obtiene desde BigQuery/ARTI. No inventar ni cargar tallas teoricas.", "M"],
  ["SKU", "Campo tecnico autogenerado", "SI", "La app lo obtiene desde BigQuery/ARTI. Obligatorio por variante.", "5327440"],
  ["EAN", "Campo tecnico autogenerado", "NO", "La app lo obtiene desde BigQuery/ARTI si existe.", "7800000000000"],
  ["Precio", "Campo tecnico autogenerado", "SI", "La app lo obtiene desde Shopify/ARTI si existe; la marca solo completa si se solicita.", "299.90"],
  ["Compare At Price", "Campo tecnico autogenerado", "NO", "Precio antes si aplica desde fuente comercial/ARTI.", ""],
  ["Stock disponible", "Campo tecnico autogenerado", "NO", "Stock eComm referencial desde BigQuery.", "12"],
  ["Tecnologia", "Tecnologias y metacampos", "NO", "Separar por coma.", "Omni-Tech, Omni-Shield"],
  ["Logo tecnologia", "Tecnologias y metacampos", "NO", "Nombre o GID de metaobjeto.", "Omni Tech, Omni Shield"],
  ["Guia de tallas", "Campo tecnico autogenerado", "NO", "La app la resuelve por categoria, tipo de prenda y genero.", "CLB_MUJER_TOPS"],
  ["Tags sugeridos", "Campo tecnico autogenerado", "NO", "La app los sugiere con marca, categoria, genero, tipo, tecnologia y Mod-Col.", "Columbia, Vestuario, Mujer, Casacas"],
  ["Handle sugerido", "Campo tecnico autogenerado", "NO", "No llenar manualmente. Formula: tipo de prenda + genero + marca + Mod-Col.", "casacas-mujer-columbia-2092991-nry"],
  ["SEO Title", "SEO y tags", "NO", "Titulo SEO opcional.", ""],
  ["SEO Description", "SEO y tags", "NO", "Descripcion SEO opcional.", ""],
  ["Fecha publicacion", "Programacion", "NO", "yyyy-mm-dd hh:mm.", ""],
  ["Observaciones", "Control", "NO", "Notas de revision.", "Ejemplo referencial, no cargar sin revisar."],
];

const productTypes = [
  ["Valor recibido", "Normalizado", "Singular", "Plural Shopify", "Categoria", "Subcategoria", "Familia guia", "Puede talla unica", "Ejemplo"],
  ["zapatilla, footwear, sneaker", "Zapatilla", "Zapatilla", "Zapatillas", "Calzado", "Zapatillas", "Calzado", "NO", "Zapatilla Hombre Konos"],
  ["casaca, chaqueta, jacket", "Casaca", "Casaca", "Casacas", "Vestuario", "Casacas", "Vestuario TOPS", "NO", "Casaca Impermeable Mujer"],
  ["polo, camiseta, t-shirt", "Polo", "Polo", "Polos", "Vestuario", "Polos", "Vestuario TOPS", "NO", "Polo Hombre"],
  ["pantalon, pants, jogger", "Pantalon", "Pantalon", "Pantalones", "Vestuario", "Pantalones", "Vestuario BOTTOMS", "NO", "Pantalon Trekking Mujer"],
  ["short, shorts, bermuda, falda", "Short", "Short", "Shorts", "Vestuario", "Shorts", "Vestuario BOTTOMS", "NO", "Short Hombre Outdoor"],
  ["gorro, beanie, jockey", "Gorro", "Gorro", "Gorros", "Accesorios", "Gorros", "Accesorios", "SI", "Gorro Cachalot"],
  ["mochila, bolso, cartera, bag", "Bolso", "Bolso", "Bolsos", "Accesorios", "Bolsos", "Accesorios", "SI", "Bolso Outdoor"],
  ["slip on, slip-on", "Slip On", "Slip On", "Slip Ons", "Calzado", "Slip Ons", "Calzado", "NO", "Slip On Vans"],
  ["crema renovadora, cleaner", "Crema renovadora", "Crema renovadora", "Cremas renovadoras", "Accesorios", "Cuidado", "Sin guia", "SI", "Crema renovadora"],
];

const sizeGuides = [
  ["Prioridad", "Marca", "Categoria", "Tipo prenda", "Genero", "Grupo edad", "Guia Shopify", "Familia", "Estado", "Regla"],
  [100, "Columbia", "Calzado", "*", "Hombre", "Adulto", "CLB_HOMBRE_CALZADO", "Calzado", "Activo", "Marca + categoria + genero"],
  [100, "Columbia", "Calzado", "*", "Mujer", "Adulto", "CLB_MUJER_CALZADO", "Calzado", "Activo", "Marca + categoria + genero"],
  [95, "Columbia", "Vestuario", "Casacas, Polos, Polerones, Camisas, Blusas, Chalecos", "Mujer", "Adulto", "CLB_MUJER_TOPS", "Vestuario TOPS", "Activo", "Marca + categoria + genero + tipo TOPS"],
  [95, "Columbia", "Vestuario", "Casacas, Polos, Polerones, Camisas, Blusas, Chalecos", "Hombre", "Adulto", "CLB_HOMBRE_TOPS", "Vestuario TOPS", "Activo", "Marca + categoria + genero + tipo TOPS"],
  [95, "Columbia", "Vestuario", "Pantalones, Shorts, Bermudas, Faldas, Leggings, Joggers", "Mujer", "Adulto", "CLB_MUJER_BOTTOMS", "Vestuario BOTTOMS", "Activo", "Marca + categoria + genero + tipo BOTTOMS"],
  [95, "Columbia", "Vestuario", "Pantalones, Shorts, Bermudas, Faldas, Leggings, Joggers", "Hombre", "Adulto", "CLB_HOMBRE_BOTTOMS", "Vestuario BOTTOMS", "Activo", "Marca + categoria + genero + tipo BOTTOMS"],
  [60, "*", "Accesorios", "*", "*", "*", "", "Accesorios", "Revision", "No asignar guia automatica si no hay confianza"],
];

const categories = [
  ["Categoria", "Subcategoria", "Familia", "Tipo prenda relacionado", "Genero permitido", "Grupo edad", "Guia esperada", "Estado", "Observaciones"],
  ["Calzado", "Zapatillas", "Calzado", "Zapatillas", "Hombre, Mujer, Unisex, Nino, Nina", "Adulto/Ninos", "Guia calzado", "Activo", "Nunca talla unica automatica"],
  ["Vestuario", "Casacas", "Vestuario TOPS", "Casacas", "Hombre, Mujer, Unisex", "Adulto/Ninos", "CLB_*_TOPS", "Activo", "Usar tallas reales de BigQuery"],
  ["Vestuario", "Polos", "Vestuario TOPS", "Polos", "Hombre, Mujer, Unisex", "Adulto/Ninos", "CLB_*_TOPS", "Activo", "Usar tallas reales de BigQuery"],
  ["Vestuario", "Pantalones", "Vestuario BOTTOMS", "Pantalones", "Hombre, Mujer, Unisex", "Adulto/Ninos", "CLB_*_BOTTOMS", "Activo", "Usar tallas reales de BigQuery"],
  ["Vestuario", "Shorts", "Vestuario BOTTOMS", "Shorts", "Hombre, Mujer, Unisex", "Adulto/Ninos", "CLB_*_BOTTOMS", "Activo", "Usar tallas reales de BigQuery"],
  ["Accesorios", "Gorros", "Accesorios", "Gorros", "Hombre, Mujer, Unisex", "Adulto/Ninos", "Revision", "Activo", "Puede ser talla unica o varias tallas segun fuente"],
];

const values = [
  ["Lista", "Valor"],
  ["Marcas", "Columbia"],
  ["Marcas", "Rockford"],
  ["Marcas", "Hush Puppies"],
  ["Marcas", "Vans"],
  ["Generos", "Hombre"],
  ["Generos", "Mujer"],
  ["Generos", "Unisex"],
  ["Categorias", "Calzado"],
  ["Categorias", "Vestuario"],
  ["Categorias", "Accesorios"],
  ["Estados", "ACTIVE"],
  ["Estados", "DRAFT"],
  ["Publicacion", "TRUE"],
  ["Publicacion", "FALSE"],
];

const errors = [
  ["Codigo", "Nivel", "Descripcion", "Causa probable", "Solucion recomendada", "Campo"],
  ["CAT-001", "Bloqueo", "Falta Mod-Col", "Input incompleto", "Completar codigo modelo-color", "Mod-Col"],
  ["CAT-002", "Bloqueo", "Variante sin SKU", "SKU no vino de BigQuery/ARTI", "Revisar Cod Int por talla", "SKU"],
  ["CAT-003", "Bloqueo", "Talla invalida", "Talla K, 0, 000 o vacia", "Usar solo talla valida fuente", "Talla"],
  ["CAT-004", "Bloqueo", "Guia incompatible", "Calzado con guia vestuario o viceversa", "Corregir guia o dejar en revision", "Guia de tallas"],
  ["CAT-005", "Advertencia", "Tipo no reconocido", "Sinonimo no existe en diccionario", "Agregar regla en catalog_rules.py", "Tipo de prenda"],
  ["CAT-006", "Advertencia", "HTML corregido", "Traia script/style/eventos o etiquetas no permitidas", "Revisar vista previa", "Body HTML"],
];

function writeMatrix(sheet, startCell, rows) {
  const startCol = startCell.match(/[A-Z]+/)[0];
  const startRow = Number(startCell.match(/\d+/)[0]);
  const colIndex = colToIndex(startCol);
  const range = sheet.getRangeByIndexes(startRow - 1, colIndex, rows.length, rows[0].length);
  range.values = rows;
  return range;
}

function colToIndex(col) {
  let n = 0;
  for (const ch of col) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n - 1;
}

function styleTable(sheet, rangeAddress, headerFill = "#0B5CAD") {
  const range = sheet.getRange(rangeAddress);
  range.format.borders = { preset: "all", style: "thin", color: "#D9E2EF" };
  const header = sheet.getRange(rangeAddress.replace(/\d+:.+/, "1:" + rangeAddress.split(":")[1].replace(/\d+/, "1")));
  header.format = { fill: headerFill, font: { bold: true, color: "#FFFFFF" } };
  range.format.wrapText = true;
  range.format.autofitColumns();
}

const workbook = Workbook.create();

const input = workbook.worksheets.add("INPUT_COMERCIAL");
input.showGridLines = false;
input.getRange("A1:AD1").values = [inputColumns.map((item) => item[0])];
input.getRange("A2:AD2").values = [inputColumns.map((item) => item[4])];
input.getRange("A3:AD3").values = [inputColumns.map((item) => item[3])];
input.getRange("A1:AD3").format.wrapText = true;
input.getRange("A1:AD1").format = { fill: "#0B5CAD", font: { bold: true, color: "#FFFFFF" } };
input.getRange("A2:AD2").format = { fill: "#EAF3FF" };
input.getRange("A3:AD3").format = { fill: "#F8FAFC", font: { color: "#526071" } };
input.getRange("A1:AD50").format.borders = { preset: "all", style: "thin", color: "#D9E2EF" };
input.freezePanes.freezeRows(1);
input.freezePanes.freezeColumns(1);
input.getRange("A:AD").format.autofitColumns();
input.getRange("A1:AD50").format.rowHeight = 24;
input.getRange("D:D").dataValidation = { rule: { type: "list", values: ["Columbia", "Rockford", "Hush Puppies", "Vans", "Patagonia", "Sorel", "Mountain Hardwear"] } };
input.getRange("E:E").dataValidation = { rule: { type: "list", values: ["Hombre", "Mujer", "Unisex", "Nino", "Nina", "Bebe"] } };
input.getRange("F:F").dataValidation = { rule: { type: "list", values: ["Calzado", "Vestuario", "Accesorios"] } };

const dict = workbook.worksheets.add("DICCIONARIO_COLUMNAS");
const dictRows = [["Nombre exacto", "Grupo", "Obligatorio", "Descripcion", "Ejemplo", "Destino Shopify", "Regla"]];
for (const [name, group, required, desc, example] of inputColumns) {
  dictRows.push([name, group, required, desc, example, name === "SKU" ? "Variant.sku" : name === "Body HTML" ? "Product.bodyHtml" : name === "Tecnologia" ? "custom.tecnologia" : "Producto / reporte", required === "SI" ? "Bloquea si esta vacio" : "Advertencia o autocompletado"]);
}
writeMatrix(dict, "A1", dictRows);
styleTable(dict, `A1:G${dictRows.length}`);

const types = workbook.worksheets.add("TIPOS_PRENDA");
writeMatrix(types, "A1", productTypes);
styleTable(types, `A1:I${productTypes.length}`, "#174EA6");

const guides = workbook.worksheets.add("GUIAS_TALLA");
writeMatrix(guides, "A1", sizeGuides);
styleTable(guides, `A1:J${sizeGuides.length}`, "#2563EB");

const cats = workbook.worksheets.add("CATEGORIAS");
writeMatrix(cats, "A1", categories);
styleTable(cats, `A1:I${categories.length}`, "#0F766E");

const vals = workbook.worksheets.add("VALORES_PERMITIDOS");
writeMatrix(vals, "A1", values);
styleTable(vals, `A1:B${values.length}`, "#6D28D9");

const err = workbook.worksheets.add("ERRORES_Y_ADVERTENCIAS");
writeMatrix(err, "A1", errors);
styleTable(err, `A1:F${errors.length}`, "#B91C1C");

for (const sheet of workbook.worksheets.items) {
  sheet.getUsedRange(true)?.format?.autofitColumns?.();
}

await fs.mkdir(outputDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(outputPath);
