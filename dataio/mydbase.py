"""
Tools for interacting w/ SQL databases
"""
import os
import sqlite3
import numpy as np


def dict2sql(dbfile, myDict, table):
    """
    Converts a dictionary to an sql database table
    """
    if os.path.exists(dbfile):
	print 'Deleting old db file.'
	os.unlink(dbfile)

    conn = sqlite3.connect(dbfile)
    cursor = conn.cursor()

    # Create the table
    #tablefields = [table]
    #tabletypes = ['text']
    #tablefmt = ['%s']
    tablefields = []
    tabletypes = []
    tablefmt = []
    for vv in myDict.values()[0].keys():
	#print myDict.values()[0][vv], type(myDict.values()[0][vv])
	if isinstance(myDict.values()[0][vv], str) \
	    or isinstance(myDict.values()[0][vv], np.unicode):
	    tabletypes += ['text']
	    tablefmt += ['"%s"']
	else:
	    tabletypes += ['real']
	    tablefmt += ['%f']
	
	tablefields += [vv]

    tablestr='('
    for ff,tt,fmt in zip(tablefields,tabletypes,tablefmt):
        tablestr += ff+' '+tt+','
    tablestr = tablestr[:-1] + ')'
    dbtuple = '('+', '.join(tablefmt)+')'
    
    createstr = 'CREATE TABLE %s %s' % (table,tablestr)
    cursor.execute(createstr)

    # Insert the values
    for kk in myDict.keys():
        dbstr = dbtuple%tuple(myDict[kk].values())		
	sqlstr = 'INSERT INTO %s VALUES %s'%(table,dbstr)
	#print sqlstr
        cursor.execute(sqlstr)
    
    conn.commit()
	

    #placeholders = ', '.join(['%s'] * len(myDict))
    #columns = ', '.join(myDict.keys())
    #print columns
    #sql = 'INSERT INTO %s ( "%s" ) VALUES ( "%s" )' % (table, columns, placeholders)
    #print sql
    #cursor.execute(sql, myDict.values())

    cursor.close()
    print 'Updated database...'

def returnQuery(dbfile,outvar,tablename,condition):
    """Returns a dictionary with the fields specified in a query
    
    Example condition:
        'Variable_Name = "RH" and start_time >= "2011-01-01 00:00:00"'
    
    """    
    
    # Open the database
    conn = sqlite3.connect(dbfile)
    c = conn.cursor()
    
    querystr = 'SELECT %s FROM %s WHERE %s'%(', '.join(outvar),tablename,condition)
    #print querystr
    query = c.execute(querystr)
    
    output = {}
    for vv in outvar:
        output.update({vv:[]})
    
    
    for row in query:
        k=-1
        for vv in outvar:
            k+=1
            output[vv].append(row[k])
    c.close()
    return output


