import { describe, expect, test } from "vitest";
import { buildUserPayload, userMatchesKeyword } from "./AdminPage";

const form = {
  email: " admin@example.edu ",
  full_name: " ",
  password: "",
  role: "student",
  is_active: false,
  totp_required: true,
};

describe("AdminPage 使用者表單 payload", () => {
  test("編輯自己時不送 role／is_active，避免把自己停用或降級", () => {
    const payload = buildUserPayload(form, { isSelf: true });
    expect(payload).not.toHaveProperty("role");
    expect(payload).not.toHaveProperty("is_active");
    expect(payload).toMatchObject({ email: "admin@example.edu", full_name: null, totp_required: true });
  });

  test("編輯別人時照送 role／is_active", () => {
    expect(buildUserPayload(form)).toMatchObject({ role: "student", is_active: false });
  });

  test("LDAP 帳號不送本地密碼，其餘有填才送", () => {
    const withPw = { ...form, password: "longpassword" };
    expect(buildUserPayload(withPw, { isLdap: true })).not.toHaveProperty("password");
    expect(buildUserPayload(withPw).password).toBe("longpassword");
    expect(buildUserPayload(form)).not.toHaveProperty("password");
  });
});

describe("AdminPage 搜尋比對", () => {
  const teacher = { email: "wang@example.edu", full_name: "王小明", role: "teacher" };

  test("比對畫面上顯示的角色名稱，不是英文角色代碼", () => {
    expect(userMatchesKeyword(teacher, "教師", "教師")).toBe(true);
    expect(userMatchesKeyword(teacher, "teacher", "教師")).toBe(false);
    expect(userMatchesKeyword(teacher, "學生", "教師")).toBe(false);
  });

  test("英文介面的角色名稱不分大小寫", () => {
    expect(userMatchesKeyword(teacher, "teach", "Teacher")).toBe(true);
  });

  test("姓名與 Email 照舊比對；沒有姓名的帳號不會出錯", () => {
    expect(userMatchesKeyword(teacher, "王小", "教師")).toBe(true);
    expect(userMatchesKeyword(teacher, "wang@", "教師")).toBe(true);
    expect(userMatchesKeyword({ ...teacher, full_name: null }, "王小", "教師")).toBe(false);
  });
});
