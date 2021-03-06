import petlib.pack
import csv
import os
from collections import Counter

def readInFile(filename):
	try:
		with open(filename, 'rb') as infile:
			lines = infile.readlines()
		for l in lines:
			#print petlib.pack.decode(l[:-1])
			print l
		print len(lines)
	except Exception, e:
		print "Error: ", str(e)

def getProvidersNames():
    filedir = 'providersNames.bi2'
    with open(filedir, "rb") as infile:
        lines = petlib.pack.decode(infile.read())
    return lines

def writeCSV():
	with open('file.csv', 'ab') as infile:
		csvW = csv.writer(infile, delimiter=',')
		data = [['A', 34], ['B', 45], ['C', 90]]
		csvW.writerows(data)

def readCSV():
	with open('file.csv', 'rb') as infile:
		csvR = csv.reader(infile)
		for row in csvR:
			print row

def test():
	for f in os.listdir('../loopix'):
		if f.startswith('messagesSent'):
			try:
				with open(f, 'rb') as infile:
					csvR = csv.reader(infile)
					for row in csvR:
						print row
			except Exception, e:
				print str(e)


def readFiles():

    import databaseConnect as dc
    databaseName = "example.db"
    db = dc.connectToDatabase(databaseName)
    c = db.cursor()
    c.execute("SELECT * FROM Users")
    allData = c.fetchall()
    daat = []
    for i in allData:
    	daat.append(str(i[5]))
    print Counter(daat)
    db.commit()				

if __name__ == "__main__":
	print getProvidersNames()
	#writeCSV()
	#readCSV()
	readFiles()
	