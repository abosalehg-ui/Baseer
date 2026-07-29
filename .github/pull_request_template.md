<!-- املأ الأقسام التالية. احذف ما لا ينطبق. -->

## المشكلة

<!-- ما الذي كان معطلاً أو ناقصاً؟ اربطه بـissue إن وُجد. -->

## الحل

<!-- ماذا تغيّر ولماذا هذا النهج تحديداً؟ -->

## التحقق

<!-- كيف تأكدت أنه يعمل؟ اذكر الاختبار الحارس إن كان إصلاح خطأ. -->

- [ ] `ruff check app tests scripts`
- [ ] `black --check app tests scripts`
- [ ] `python scripts/check_structure.py`
- [ ] `mypy app`
- [ ] `QT_QPA_PLATFORM=offscreen pytest --cov=app --cov-fail-under=60`

## قائمة تحقق

- [ ] إصلاح الخطأ مصحوب باختبار يفشل قبله ويمر بعده
- [ ] لا SQL خام ولا وصول لـ`Service._db` من `app/ui/`
- [ ] الألوان الجديدة من `app/ui/theme.py` وتباينها ≥ 4.5:1
- [ ] الأزرار الجديدة لها `setAccessibleName`
- [ ] الكتابات متعددة الخطوات داخل `db.transaction()`
- [ ] التوثيق مُحدَّث إن تغيّر سلوك ظاهر للمستخدم
- [ ] `CHANGELOG.md` مُحدَّث
