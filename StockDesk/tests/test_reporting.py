import unittest
from datetime import date
from reporting import filter_stock, filter_movements


class ReportingTests(unittest.TestCase):
    def test_stock_search_and_reorder(self):
        rows = [{'Article ID': 'A', 'Article': 'Blue bag', 'HSN': '4202', 'Status': 'REORDER'},
                {'Article ID': 'B', 'Article': 'Blue box', 'HSN': '4819', 'Status': 'OK'}]
        self.assertEqual(filter_stock(rows, ' BLUE ', True), rows[:1])
        self.assertEqual(filter_stock(rows, '4819'), rows[1:])

    def test_india_date_boundary_and_location(self):
        rows = [{'at': '2026-09-21T20:00:00Z', 'article': 'A', 'location': 'Main'},
                {'at': '2026-09-22T03:00:00Z', 'article': 'A', 'location': 'Other'}]
        result = filter_movements(rows, date(2026, 9, 22), date(2026, 9, 22), 'Main', 'A')
        self.assertEqual(result, rows[:1])
        self.assertIsNot(result[0], rows[0])


if __name__ == '__main__':
    unittest.main()
