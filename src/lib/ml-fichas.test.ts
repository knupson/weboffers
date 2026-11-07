import { expect, it } from "vitest";
import { loadMlSheet, validMlSheet } from "./ml-fichas";

const now = Date.parse("2026-11-07T15:00:00Z");
const sheet = {
  fetched: "2026-11-07", name: "Disco Ssd Externo 1tb Sandisk Extreme",
  attributes: [["Capacidad", "4 TB"]], mainFeatures: ["Capacidad de 4 TB"],
  rawAttributes: [{ id: "CAPACITY", value_name: "4 TB" }, { id: "MODEL", value_name: "SDSSDE61-4T00" }],
};
it("descarta completa la ficha MLA54977132 de SanDisk con 1tb en el nombre y 4 TB en atributos", () => {
  expect(validMlSheet("SanDisk Extreme 1 TB", sheet, now)).toBeNull();
});
it("acepta cantidades equivalentes con espacios y mayúsculas", () => {
  expect(validMlSheet("SanDisk 4tb", { ...sheet, name: "SanDisk 4 TB" }, now)).not.toBeNull();
});
it("reconoce memoria y capacidad de almacenamiento y permite nombres sin cantidades", () => {
  // La RAM sólo se contrasta con dos cantidades en el nombre: la cubre el test de casos reales del 07/11.
  for (const id of ["INTERNAL_MEMORY", "MEMORY_CAPACITY", "STORAGE_CAPACITY", "SSD_DATA_STORAGE_CAPACITY", "HARD_DRIVE_CAPACITY"]) {
    expect(validMlSheet("SSD 1TB", { ...sheet, rawAttributes: [{ id, value_name: "4 TB" }] }, now)).toBeNull();
  }
  expect(validMlSheet("SSD", { ...sheet, name: "SSD" }, now)).not.toBeNull();
});
it("rechaza fichas vencidas, futuras, malformadas y archivos ausentes", () => {
  for (const fetched of ["2026-10-30", "2026-11-08", "ayer"]) expect(validMlSheet("SSD", { ...sheet, fetched }, now)).toBeNull();
  expect(validMlSheet("SSD", { ...sheet, fetched: "2026-10-31", name: "SSD" }, now)).not.toBeNull();
  expect(validMlSheet("SSD", { ...sheet, rawAttributes: undefined }, now)).toBeNull();
  expect(loadMlSheet(undefined, "SSD", now)).toBeNull();
});

it("mismo criterio que el worker con los casos reales del 07/11", () => {
  const hoja = (name: string, ...raw: [string, string][]) => ({ ...sheet, name, attributes: [], mainFeatures: [],
    rawAttributes: raw.map(([id, value_name]) => ({ id, value_name })) });
  expect(validMlSheet("WD Green SSD SATA 1TB", hoja("WesternDigital WD Green SSD 1 TB", ["CAPACITY", "2 TB"]), now)).toBeNull();
  expect(validMlSheet("Xiaomi Redmi Pad 2 256GB", hoja("Xiaomi Redmi Pad 2 256 GB", ["INTERNAL_MEMORY", "256 GB"], ["MAX_MEMORY_SUPPORTED_CAPACITY", "2 TB"]), now)).not.toBeNull();
  expect(validMlSheet("ASUS Dual RTX 3050 6GB", hoja("Placa Asus Dual Rtx 3050 6gb", ["MEMORY_DATA_SPEED", "3 GB/s"]), now)).not.toBeNull();
  expect(validMlSheet("Samsung A37 5G 256GB", hoja("Samsung Galaxy A37 5G 256 GB", ["RAM", "8 GB"]), now)).not.toBeNull();
  expect(validMlSheet("Xiaomi Pad 2 128GB 4GB", hoja("Xiaomi Pad 2 128 GB 4 GB", ["RAM", "8 GB"]), now)).toBeNull();
});

it("descarta si el nombre de ML y el nuestro no comparten cantidad (2TB vs 1TB)", () => {
  const hoja = { ...sheet, name: "SSD Samsung 980 1TB", rawAttributes: [{ id: "INTERNAL_MEMORY", value_name: "1 TB" }] };
  expect(validMlSheet("SSD Samsung 980 2TB", hoja, now)).toBeNull();
  expect(validMlSheet("SSD Samsung 980 1TB", hoja, now)).not.toBeNull();
});
