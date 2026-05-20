import sys

try:
    import win32com.client
    print("win32com.client is installed!")
    
    # Try to launch Excel headlessly
    try:
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        print("Excel launched successfully!")
        excel.Quit()
    except Exception as e:
        print(f"Error launching Excel: {e}")
except ImportError:
    print("win32com.client is not installed.")
