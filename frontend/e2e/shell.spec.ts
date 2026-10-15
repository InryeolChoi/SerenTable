import { test, expect } from '@playwright/test';

test('모바일에서 참가자·운영자 준비 화면 이동과 새로고침이 가능하다', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '우연한 식탁', exact: true })).toBeVisible();
  await page.getByRole('link', { name: '참가자 화면' }).click();
  await expect(page.getByRole('heading', { name: '참가자 화면' })).toBeVisible();
  await page.reload();
  await expect(page.getByText('아직 신청과 로그인 기능을 제공하지 않습니다.')).toBeVisible();
  await page.getByRole('link', { name: '운영자 화면' }).click();
  await page.reload();
  await expect(page.getByRole('heading', { name: '운영자 화면' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
