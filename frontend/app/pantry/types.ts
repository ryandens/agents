export type StorageLocation = "pantry" | "fridge" | "freezer";

export type Category =
  | "produce"
  | "dairy"
  | "meat"
  | "seafood"
  | "grains"
  | "legumes"
  | "condiments"
  | "spices"
  | "beverages"
  | "snacks"
  | "baking"
  | "canned"
  | "frozen"
  | "other";

export type Unit =
  | "lbs"
  | "oz"
  | "kg"
  | "g"
  | "cups"
  | "tbsp"
  | "tsp"
  | "fl_oz"
  | "ml"
  | "liters"
  | "gallons"
  | "count"
  | "bunch"
  | "head"
  | "clove"
  | "loaf"
  | "can"
  | "bottle"
  | "box"
  | "bag"
  | "jar";

export interface PantryItem {
  id: string;
  name: string;
  brand: string | null;
  category: Category;
  storage_location: StorageLocation;
  quantity: number;
  unit: Unit;
  purchase_date: string | null;
  expiration_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PantryItemCreate {
  name: string;
  brand: string | null;
  category: Category;
  storage_location: StorageLocation;
  quantity: number;
  unit: Unit;
  purchase_date: string | null;
  expiration_date: string | null;
  notes: string | null;
}

export type PantryItemUpdate = Partial<PantryItemCreate>;

export const CATEGORY_LABELS: Record<Category, string> = {
  produce: "Produce",
  dairy: "Dairy",
  meat: "Meat",
  seafood: "Seafood",
  grains: "Grains",
  legumes: "Legumes",
  condiments: "Condiments",
  spices: "Spices",
  beverages: "Beverages",
  snacks: "Snacks",
  baking: "Baking",
  canned: "Canned",
  frozen: "Frozen",
  other: "Other",
};

export const UNIT_GROUPS: { label: string; units: Unit[] }[] = [
  { label: "Weight", units: ["lbs", "oz", "kg", "g"] },
  { label: "Volume", units: ["cups", "tbsp", "tsp", "fl_oz", "ml", "liters", "gallons"] },
  { label: "Count", units: ["count", "bunch", "head", "clove", "loaf"] },
  { label: "Container", units: ["can", "bottle", "box", "bag", "jar"] },
];

export const BACKEND = process.env.NEXT_PUBLIC_BACKEND ?? "";
