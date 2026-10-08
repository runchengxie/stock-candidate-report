import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [payloadPath, outputPath, previewFlag] = process.argv.slice(2);
const payload = JSON.parse(await fs.readFile(payloadPath, "utf8"));
const workbook = Workbook.create();
const safe = value => typeof value === "string" && value.startsWith("=") ? "'" + value : value;
for (const [index, spec] of payload.sheets.entries()) {
  const sheet = workbook.worksheets.add(spec.name);
  sheet.showGridLines = false;
  const rows = spec.rows.map(row => row.map(safe));
  sheet.getRangeByIndexes(0, 0, rows.length, rows[0].length).values = rows;
  const used = sheet.getRangeByIndexes(0, 0, rows.length, rows[0].length);
  used.format.font = { name: "Arial", size: 10, color: "#172B4D" };
  used.format.verticalAlignment = "center";
  used.format.rowHeight = 23;
  used.format.columnWidth = 16;
  sheet.getRange("A2").format.font = {name: "Arial", size: 14, bold: true};
  sheet.getRangeByIndexes(4, 0, 1, rows[0].length).format = {
    fill: "#203864", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    wrapText: true, rowHeight: 40, horizontalAlignment: "center", verticalAlignment: "center"
  };
  sheet.getRange("A3").format.font = {name:"Arial", size:10, italic:true, color:"#52657A"};
  sheet.getRange("A4").format.font = {name:"Arial", size:10, color:"#9C5700"};
  for (const [col, width] of Object.entries(spec.widths)) {
    sheet.getRangeByIndexes(0, Number(col), rows.length, 1).format.columnWidth = width;
  }
  for (const [col, fmt] of Object.entries(spec.formats)) {
    if (rows.length > 5) sheet.getRangeByIndexes(5, Number(col), rows.length-5, 1).setNumberFormat(fmt);
  }
  if (rows.length > 5) {
    const table = sheet.tables.add(sheet.getRangeByIndexes(4, 0, rows.length-4, rows[0].length),
                                   true, index === 0 ? "CandidateStocks" : "InputDetails");
    table.showFilterButton = true;
  }
  sheet.freezePanes.freezeRows(5);
  sheet.freezePanes.freezeColumns(index === 0 ? 3 : 2);
  sheet.tabColor = index === 0 ? "#203864" : "#72859C";
}
workbook.recalculate();
const inspect = await workbook.inspect({kind:"table", range:"增长和估值!A5:G9",
  include:"values", tableMaxRows:5, tableMaxCols:7, maxChars:1000});
await fs.writeFile(outputPath + ".verification.json", inspect.ndjson ?? "");
const errors = await workbook.inspect({kind:"match", searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!",
  options:{useRegex:true, maxResults:20}, maxChars:1000});
await fs.writeFile(outputPath + ".errors.json", errors.ndjson ?? "");
if (previewFlag === "preview") {
  for (const [name, range, suffix] of [["增长和估值","A1:G12","prices"],
      ["增长和估值","H5:U12","financials"], ["数据明细","A1:H12","detail"]]) {
    const blob = await workbook.render({sheetName:name, range, scale:1.5, format:"png"});
    await fs.writeFile(outputPath + "." + suffix + ".png", new Uint8Array(await blob.arrayBuffer()));
  }
}
await (await SpreadsheetFile.exportXlsx(workbook)).save(outputPath);
