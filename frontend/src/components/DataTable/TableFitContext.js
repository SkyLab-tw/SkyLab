import { createContext, useContext } from "react";

/* useTableFit 的結果，由 <DataTable fit> 提供給表格裡的列與儲存格：
   自己畫 <td> 的列（群組列、建立中的列）要跳過收起的欄，主欄要把收起的內容畫進來。
   context 獨立成檔，元件檔混輸出 context 會讓熱更新時 useContext 拿到 null。
   沒有 Provider（表格沒用 fit）時什麼都不收 */
const NO_FIT = Object.freeze({ isFolded: () => false, overflow: false });

export const TableFitContext = createContext(NO_FIT);

export function useTableFitContext() {
  return useContext(TableFitContext);
}
