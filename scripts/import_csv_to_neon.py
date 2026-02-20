"""Script to read CSV files, create tables, and upload to NeonDB using pandas and psycopg2."""
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values
from sqlalchemy import create_engine, inspect, text
from backend.app.config import get_settings


def get_postgres_type(dtype):
    """Map pandas dtype to PostgreSQL type."""
    dtype_str = str(dtype)
    
    if 'int64' in dtype_str:
        return 'BIGINT'
    elif 'int32' in dtype_str or 'int' in dtype_str:
        return 'INTEGER'
    elif 'float64' in dtype_str or 'float' in dtype_str:
        return 'DOUBLE PRECISION'
    elif 'bool' in dtype_str:
        return 'BOOLEAN'
    elif 'datetime64' in dtype_str:
        return 'TIMESTAMP'
    elif 'object' in dtype_str:
        return 'TEXT'
    else:
        return 'TEXT'


def create_table_from_dataframe(conn, df: pd.DataFrame, table_name: str, drop_if_exists: bool = True):
    """
    Create a PostgreSQL table based on DataFrame schema.
    
    Args:
        conn: psycopg2 connection
        df: pandas DataFrame
        table_name: Name of the table to create
        drop_if_exists: Whether to drop existing table
    """
    cursor = conn.cursor()
    
    try:
        # Drop table if exists
        if drop_if_exists:
            cursor.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                sql.Identifier(table_name)
            ))
            print(f"✓ Dropped existing table '{table_name}' (if existed)")
        
        # Build CREATE TABLE statement
        columns = []
        for col_name, dtype in df.dtypes.items():
            pg_type = get_postgres_type(dtype)
            # Sanitize column names (replace spaces, special chars)
            clean_col_name = col_name.lower().replace(' ', '_').replace('-', '_')
            columns.append(f'"{clean_col_name}" {pg_type}')
        
        create_stmt = f"CREATE TABLE {table_name} ({', '.join(columns)})"
        cursor.execute(create_stmt)
        conn.commit()
        print(f"✓ Created table '{table_name}' with {len(columns)} columns")
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()


def bulk_insert_dataframe(conn, df: pd.DataFrame, table_name: str, batch_size: int = 1000):
    """
    Bulk insert DataFrame into PostgreSQL table using execute_values (fastest method).
    
    Args:
        conn: psycopg2 connection
        df: pandas DataFrame
        table_name: Name of the table
        batch_size: Number of rows to insert per batch
    """
    cursor = conn.cursor()
    
    try:
        # Clean column names to match table
        df.columns = [col.lower().replace(' ', '_').replace('-', '_') for col in df.columns]
        
        # Replace NaN with None for proper NULL handling
        df = df.where(pd.notnull(df), None)
        
        # Prepare column names
        columns = list(df.columns)
        col_names = ', '.join([f'"{col}"' for col in columns])
        
        # Convert DataFrame to list of tuples
        values = [tuple(row) for row in df.itertuples(index=False, name=None)]
        
        # Bulk insert using execute_values (much faster than individual inserts)
        query = f"INSERT INTO {table_name} ({col_names}) VALUES %s"
        
        total_rows = len(values)
        for i in range(0, total_rows, batch_size):
            batch = values[i:i + batch_size]
            execute_values(cursor, query, batch)
            print(f"  Inserted {min(i + batch_size, total_rows)}/{total_rows} rows...", end='\r')
        
        conn.commit()
        print(f"\n✓ Successfully inserted {total_rows} rows into '{table_name}'")
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()


def get_psycopg2_connection():
    """Get a direct psycopg2 connection to NeonDB."""
    settings = get_settings()
    
    # Parse DATABASE_URL
    # Format: postgresql://user:password@host:port/dbname?sslmode=require
    db_url = settings.database_url
    
    # Extract components
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', '')
    
    # Split credentials and host
    credentials, rest = db_url.split('@')
    user, password = credentials.split(':')
    
    # Split host and database
    host_port, db_params = rest.split('/')
    host = host_port.split(':')[0]
    port = host_port.split(':')[1] if ':' in host_port else '5432'
    
    # Get database name (before query params)
    dbname = db_params.split('?')[0]
    
    # Connect with psycopg2
    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode='require'  # Neon requires SSL
    )
    
    return conn


def verify_table_data(conn, table_name: str):
    """Verify data in table and show sample."""
    cursor = conn.cursor()
    
    try:
        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"\n📊 Table '{table_name}' statistics:")
        print(f"   Total rows: {count}")
        
        # Get column info
        cursor.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """)
        columns = cursor.fetchall()
        print(f"   Columns: {len(columns)}")
        for col_name, col_type in columns[:5]:  # Show first 5 columns
            print(f"     - {col_name}: {col_type}")
        if len(columns) > 5:
            print(f"     ... and {len(columns) - 5} more")
        
        # Show sample data
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
        rows = cursor.fetchall()
        if rows:
            print(f"\n   Sample data (first 3 rows):")
            for i, row in enumerate(rows, 1):
                print(f"     Row {i}: {row[:3]}...")  # Show first 3 values
        
    finally:
        cursor.close()


def create_table_from_csv(csv_path: str, table_name: str, method: str = 'psycopg2'):
    """
    Read CSV file, create table, and upload data to NeonDB.
    
    Args:
        csv_path: Path to the CSV file
        table_name: Name of the table to create
        method: 'psycopg2' (fast) or 'pandas' (simple)
    """
    print(f"\n{'='*60}")
    print(f"Processing: {Path(csv_path).name}")
    print(f"Table: {table_name}")
    print(f"Method: {method}")
    print(f"{'='*60}\n")
    
    # Read CSV file with pandas
    print("📁 Reading CSV file...")
    df = pd.read_csv(csv_path)
    print(f"✓ Loaded {len(df)} rows and {len(df.columns)} columns")
    print(f"   Columns: {list(df.columns)}")
    
    # Show data types
    print(f"\n📋 Data types:")
    for col, dtype in df.dtypes.items():
        print(f"   {col}: {dtype} → {get_postgres_type(dtype)}")
    
    if method == 'psycopg2':
        # Use psycopg2 for faster bulk insert
        print(f"\n📤 Using psycopg2 bulk insert (fast method)...")
        conn = get_psycopg2_connection()
        
        try:
            # Create table
            create_table_from_dataframe(conn, df, table_name, drop_if_exists=True)
            
            # Bulk insert data
            bulk_insert_dataframe(conn, df, table_name, batch_size=1000)
            
            # Verify
            verify_table_data(conn, table_name)
            
        finally:
            conn.close()
            
    else:
        # Use pandas to_sql (simpler but slower)
        print(f"\n📤 Using pandas to_sql (simple method)...")
        settings = get_settings()
        engine = create_engine(settings.database_url)
        
        df.to_sql(
            name=table_name,
            con=engine,
            if_exists='replace',
            index=False,
            chunksize=1000,
            method='multi'  # Use multi-row INSERT
        )
        print(f"✓ Successfully uploaded {len(df)} rows to '{table_name}'")
        
        engine.dispose()


def import_all_csv_files(method: str = 'psycopg2'):
    """
    Import all CSV files from the directory specified in Settings.data_dir.
    
    Args:
        method: 'psycopg2' or 'pandas'
    """
    settings = get_settings()
    
    # Get CSV directory from Settings
    csv_dir = settings.data_dir
    
    print(f"\n{'='*60}")
    print(f"NeonDB CSV Import from Folder")
    print(f"{'='*60}")
    
    # Display connection info (masked password)
    db_url = settings.database_url
    host_info = db_url.split('@')[1].split('/')[0] if '@' in db_url else 'unknown'
    print(f"Database host: {host_info}")
    print(f"CSV directory: {csv_dir}")
    print(f"Import method: {method}")
    
    # Resolve path
    data_path = Path(csv_dir)
    if not data_path.is_absolute():
        data_path = project_root / csv_dir
    
    # Check if directory exists
    if not data_path.exists():
        print(f"\n✗ Directory not found: {data_path}")
        print(f"   Please check DATA_DIR in your config.py or .env file")
        return
    
    if not data_path.is_dir():
        print(f"\n✗ Path is not a directory: {data_path}")
        return
    
    # Find all CSV files
    csv_files = list(data_path.glob("*.csv"))
    
    if not csv_files:
        print(f"\n⚠ No CSV files found in {data_path}")
        return
    
    print(f"\nFound {len(csv_files)} CSV file(s):")
    for csv_file in csv_files:
        print(f"  - {csv_file.name}")
    
    print()
    
    # Process each CSV file
    success_count = 0
    for csv_file in csv_files:
        # Use filename (without .csv) as table name
        table_name = csv_file.stem.lower().replace('-', '_').replace(' ', '_')
        try:
            create_table_from_csv(str(csv_file), table_name, method=method)
            success_count += 1
        except Exception as e:
            print(f"\n✗ Error processing {csv_file.name}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n{'='*60}")
    print(f"✓ Import completed: {success_count}/{len(csv_files)} successful")
    print(f"{'='*60}\n")


# def import_single_csv(csv_path: str, table_name: str = None, method: str = 'psycopg2'):
#     """
#     Import a single CSV file.
    
#     Args:
#         csv_path: Path to CSV file
#         table_name: Optional table name (defaults to filename)
#         method: 'psycopg2' or 'pandas'
#     """
#     csv_file = Path(csv_path)
#     if not csv_file.exists():
#         print(f"✗ File not found: {csv_path}")
#         return
    
#     if table_name is None:
#         table_name = csv_file.stem.lower().replace('-', '_').replace(' ', '_')
    
#     create_table_from_csv(csv_path, table_name, method=method)


def main():
    """Main function with CLI arguments."""
    # import argparse
    
    # parser = argparse.ArgumentParser(
    #     description='Import CSV files to NeonDB using pandas and psycopg2',
    #     epilog='Example: python scripts/import_csv_to_neon.py'
    # )
    # parser.add_argument(
    #     '--file',
    #     type=str,
    #     help='Path to a single CSV file to import'
    # )
    # parser.add_argument(
    #     '--table',
    #     type=str,
    #     help='Table name for single file import (defaults to filename)'
    # )
    # parser.add_argument(
    #     '--method',
    #     type=str,
    #     choices=['psycopg2', 'pandas'],
    #     default='psycopg2',
    #     help='Import method: psycopg2 (fast) or pandas (simple). Default: psycopg2'
    # )
    
    # args = parser.parse_args()
    
    try:
        # if args.file:
        #     # Import single file
        #     import_single_csv(args.file, args.table, method=args.method)
        # else:
            # Default: import all CSV files from Settings.data_dir
            import_all_csv_files(method='psycopg2')
    
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()