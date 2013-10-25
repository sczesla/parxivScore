try:
  import feedparser as fp
except ImportError, e:
  print
  print "ERROR:"
  print "   You need to have 'feedparser' installed."
  print
  raise e

import pickle
import re
import numpy as np
import textwrap
import copy
import argparse

class ParxivFeed:
  """
    Manage the collection of articles.
    
    Attributes
    ----------
    articles : dictionary
        Maps a number (starting with 1) onto
        article information. The latter is a
        dictionary with the following keys:
          - full: Complete information as given
          in arXiv.
          - title: Title as a string.
          - subcat: The subcategory (e.g., TBD)
          - abstract: The abstract as a string (no
          newlines).
          - authors: List of strings giving the
          author names as specified in arXiv.
          - authorsDecomp: List of tuples
          The decomposed author names.
  """
  
  def _decomposeName(self, n):
    """
      Decompose author name.
      
      Parameters
      ----------
      n : string
          The name as given in arXiv.
      
      Returns
      -------
      sn : string
          The surname
      gn : list of strings
          Given names as specified in arXiv
      inits : list of strings
          List of initials.
    """
    # Insert a space after a dot, if not a hyphen follows
    s = ""
    for i, c in enumerate(n):
      s += c
      if (c == '.') and (n[i+1] != '-'):
        s += ' '
    parts = s.split()
    surname = []
    for i, p in enumerate(parts[::-1]):
      if i == 0:
        surname.insert(0, p)
        continue
      if p.find('.') != -1:
        break
      if p[0].isupper():
        break
      surname.insert(0, p)
    
    # Compose surname
    sn = ' '.join(surname)
    gn = parts[0:-len(surname)]
    
    # Get initials
    inits = []
    for gnp in gn:
      if gnp.find('.') != -1:
        # It is already an initial
        inits.append(gnp)
        continue
      s = ""
      for c in gnp:
        if c.isupper():
          s += c + "."
        if c == "-":
          s += "-"
      inits.append(s)

    return sn, gn, inits
  
  def _createArticleData(self, feed):
    """
      Decompose the feed information.
      
      Parameters
      ----------
      feed : feedparser feed
          The arxiv feed.
    """
    for i, e in enumerate(feed.entries):
      a = {}
      # Assign full info
      a["full"] = copy.copy(e)
      # Get title
      a["title"] = e.title
      # Separate the (arXiv:...) part
      r = re.match("^(.*)\s*\((arXiv.*)\)\s*$", e.title)
      a["titlePure"] = None
      a["titleFinish"] = None
      if r is not None:
        a["titlePure"] = r.group(1)
        a["titleFinish"] = r.group(2)
      # Determine subcategory (None if this is impossible)
      a["subcat"] = None
      r = re.match(".*\(arXiv:.+\[astro-ph\.(\w+)\].*$", a["title"])
      if r is not None:
        a["subcat"] = r.group(1)
      # Get the abstract and remove newlines and paragraphs
      a["abstract"] = str(e.summary).replace("\n", " ").replace("\r", '').replace("<p>", "").replace("</p>","")
      # Get authors
      a["authors"] = []
      a["authorsDecomp"] = []
      for el in e.author_detail["name"].split(','):
        r = re.match(".*\>(.*)\<.*", el)
        if r is None:
          continue
        a["authors"].append(r.group(1))
        a["authorsDecomp"].append(self._decomposeName(a["authors"][-1]))
      
      self.articles[i+1] = a.copy()
  
  def _extractSection(self, fn, sec):
    """
      Extract a section from configuration file.
      
      Parameters
      ----------
      fn : string
          Name of configuration file.
      sec : string
          Name of the section.
      
      Returns
      -------
      Content : list of strings
          The content of that section. None, if
          noting has been found.
    """
    lines = []
    amin = False
    for l in open(fn):
      r = re.match("^\s*\[(.*)\]\s*$", l)
      if (r is None) and amin:
        # This is a relevant line
        lines.append(l)
        continue
      elif (r is not None) and amin:
        # Encountered another section
        return lines
      if (r is not None) and (r.group(1) == sec):
        # Entering the relevant section
        amin = True
        continue
    if amin:
      return lines
    else:
      return None
          
  def _loadScoringData(self, fn):
    """
      Load the scoring details from a file.
      
      Parameters
      ----------
      fn : string
          The name of the file holding the
          scoring details.
    """
    try:
      open(fn)
    except IOError, e:
      print
      print "ERROR:"
      print "   Could not open configuration file: ", fn
      print "   Check filanme."
      print
      raise e
    self._titAbsRegex = []
    for l in self._extractSection(fn, "Buzzwords"):
      r = re.match("\s*\"(.*)\"\s+(.*)", l)
      if r is None:
        continue
      self._titAbsRegex.append((r.group(1), float(r.group(2))))
    
    self._authors = []
    for l in self._extractSection(fn, "Authors"):
      r = re.match("\s*\"(.*)\"\s+(.*)", l)
      if r is None:
        continue
      # Split author names and initials
      self._authors.append(tuple(map(str.strip, r.group(1).split(','))) + (float(r.group(2)),))    
    
    self._subcats = []
    for l in self._extractSection(fn, "Subcat"):
      r = re.match("\s*\"(.*)\"\s+(.*)", l)
      if r is None:
        continue
      self._subcats.append((r.group(1), float(r.group(2))))     
  
  
  def _scoreTitle(self, k):
    """
      Calculate score for title
      
      Parameters
      ----------
      k : int
          Identifier for article.
    """
    score = 0.0
    # Scoring details
    sd = []
    for reg in self._titAbsRegex:
      r = re.findall(reg[0], self.articles[k]["title"])
      score += float(len(r)) * reg[1]
      if len(r) > 0:
        # There is at least one match
        if len(r) > 1:
          # More than one match
          sd.append("%d*(%+d)=%+d" % (len(r), int(reg[1]), len(r)*int(reg[1])))
        else:
          # Only one match
          sd.append("%+d" % (len(r)*int(reg[1])))
        sd[-1] += " (" + reg[0] + ")"
    if len(sd) > 0:
      return score, "Title: " + ', '.join(sd)
    return score, ""
    

  def _scoreAbstract(self, k):
    """
      Calculate score for abstract.
    
      Parameters
      ----------
      k : int
          Identifier for article.
    """
    score = 0.0
    # Scoring details
    sd = []
    for reg in self._titAbsRegex:
      r = re.findall(reg[0], self.articles[k]["abstract"])
      score += float(len(r)) * reg[1]
      if len(r) > 0:
        # At least one match
        if len(r) > 1:
          sd.append("%d*(%+d)=%+d" % (len(r), int(reg[1]), len(r)*int(reg[1])))
        else:
          sd.append("%+d" % (len(r)*int(reg[1])))
        sd[-1] += " (" + reg[0] + ")"
    if len(sd) > 0:
      return score, "Abstract: " + ', '.join(sd)
    else:
      return score, ""
        
  def _scoreAuthors(self, k):
    """
      Calculate score for author list.
    
      Parameters
      ----------
      k : int
          Identifier for article.
    """
    score = 0.0
    # Scoring details
    sd = []
    # Score authors
    for searchName in self._authors:
      for a in self.articles[k]["authorsDecomp"]:
        if a[0] == searchName[0]:
          # Surname matches
          # Check whether all given initials are found
          allInitsFound = True
          if len(searchName) > 2:
            # There are initials, which have to be considered
              for i in range(1, len(searchName)-1):
                allInitsFound = (allInitsFound and (searchName[i] in a[2]))
          if allInitsFound:
            score += searchName[-1]
            sd.append(str(int(searchName[-1])) + " (" + ' '.join(searchName[0:-1]) + ")")
      if len(sd) > 0:
        return score, "Authors: " + ', '.join(sd)
      else:
        return score, ""
  
  def _scoreSubcategory(self, k):
    """
      Calculate score for subcategory.
    
      Parameters
      ----------
      k : int
          Identifier for article.
    """
    score = 0.0
    # Scoring details
    sd = []
    for sc in self._subcats:
      if self.articles[k]["subcat"] == sc[0]:
        score += sc[1]
        sd.append(str(int(sc[1])) + " (" + sc[0] + ")")
    if len(sd) > 0:
      return score, "Subcategory: " + ', '.join(sd)
    else:
      return score, ""
  
  def _score(self):
    """
      Calculate score for the articles.
    """
    self._scores = {}
    for k in self.articles.keys():      
      # Score title
      tiScore, tiD = self._scoreTitle(k)
      # Score abstract
      abScore, abD = self._scoreAbstract(k)
      # Score authors
      auScore, auD = self._scoreAuthors(k)
      # Score subcategory
      scScore, scD = self._scoreSubcategory(k)
     
      # Combine scores
      self._scores[k] = tiScore + abScore + auScore + scScore
      # Combine scoring details
      sd = "Scoring details: "
      for d in [tiD, abD, auD, scD]:
        if len(d) == 0:
          continue
        sd += d + "; "
      sd = sd.rstrip("; ")
      self.articles[k]["scoreDetails"] = sd
        
  def _scoreSort(self):
    """
    Get the order of keys, which sorts by score.
    
    Returns
    -------
    Key list : List of integers
        The list of keys for the 'articles' attribute, which
        sorts the articles with respect to scoring.
    """
    l = (np.argsort(self._scores.values()) + 1)[::-1]
    return l
  
  def _htmlOut(self, sortkeys):
    """
      Generate HTML-formatted output.
      
      Returns
      -------
      HTML code : list of strings
          The HTML code. No newlines at end of line.
    """
    lines = ["<!DOCTYPE html>\n", "<html>\n", "<body>\n", "<div>\n", "<table border=\"2\">\n"]
    lines.append("<tr>\n")
    lines.extend(["<th>", "Rank/\nScore", "</th>\n"])
    lines.extend(["<th>", "Article information", "</th>\n"])
    lines.append("</tr>\n")    
    for i, sk in enumerate(sortkeys, 1):
      lines.append("<tr>\n")
      lines.extend(["<td rowspan=\"1\">", "<b>%3d</b>" % (i), "</td>\n"])
      lines.extend(["<td><b>", str(self.articles[sk]["titlePure"]), "</b></td>\n"])
      lines.append("</tr>\n")
      lines.append("<tr>\n")
      scoreDetails = "\n".join(textwrap.wrap(self.articles[sk]["scoreDetails"], 60))
      lines.extend(["<td rowspan=\"3\">", ("<div title=\"" + scoreDetails + "\"> %5.0f </div>") % (self._scores[sk]), "</td>\n"])
      lines.extend(["<td>", "<br>".join(textwrap.wrap(','.join(self.articles[sk]["authors"]), 120)),"</td>"])
      lines.append("</tr>\n")
      lines.append("<tr>\n")
      lines.extend(["<td>", "<br>\n".join(textwrap.wrap(self.articles[sk]["abstract"], 120)) ,"</td>"])
      lines.append("</tr>\n")
      lines.append("<tr>\n")
      lines.extend(["<td>", "<a href=\"", self.articles[sk]["full"].link, "\">", self.articles[sk]["titleFinish"], "</a>" ,"</td>"])
      lines.append("</tr>\n")
    lines.extend(["</div>\n", "</table>\n", "</body>\n", "</html>\n"])
    
    return lines
  
  def _download(self):
    """
      Download the arXiv atro-ph feed.
    """
    feed = fp.parse("http://arxiv.org/rss/astro-ph")
    return feed
  
  def __init__(self, feed=None, htmlout="tmp.html", saveFeed=None, configf="parxiv.config"):
    
    if feed is None:
      # Download feed
      print "Downloading feed"
      feed = self._download()
    if saveFeed is not None:
      # Save feed information to file
      print "Saving feed to file: ", saveFeed
      pickle.dump(feed, open(saveFeed, 'w'))
    
    # Set-up article information
    self.articles = {}
    self._createArticleData(feed)
    # Load scoring data
    self._loadScoringData(configf)
    # Score the articles
    self._score()
    # Sort with respect to scoring
    sortkeys = self._scoreSort()
    ll = self._htmlOut(sortkeys)
    print "Writing html output to file: ", htmlout
    open(htmlout, 'w').writelines(ll)


parser = argparse.ArgumentParser(description='Parse the arXiv RSS--astro-ph feed.')
parser.add_argument('--htmloutput', default="parxivScore.html",
                   help='Filename to write HTML output (default tmp.html).')
parser.add_argument('--saveFeed', default="astroph.pickle",
                   help='Filename for saving the feed information (default is astroph.pickle). Set to None to avoid saving.')
parser.add_argument('--loadFeed', default=None,
                   help='If given, the feed is read from file and not downloaded.')
parser.add_argument('--cf', default="parxiv.config",
                   help="The config file to be used (default is 'parxiv.config').")

args = parser.parse_args()

feed = None
if args.loadFeed is not None:
  feed = pickle.load(open(args.loadFeed))

if args.saveFeed == "None":
  args.saveFeed = None
  
ParxivFeed(feed=feed, htmlout=args.htmloutput, saveFeed=args.saveFeed, configf=args.cf)

